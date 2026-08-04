#include "onero_interface_cpp.h"
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

using onero_api::JointArray;

static std::string html;

static std::map<std::string,std::string> query(const std::string& path){
  std::map<std::string,std::string> out; auto p=path.find('?'); if(p==std::string::npos)return out;
  std::stringstream ss(path.substr(p+1)); std::string item;
  while(std::getline(ss,item,'&')){auto e=item.find('=');if(e!=std::string::npos)out[item.substr(0,e)]=item.substr(e+1);}
  return out;
}
static void reply(int fd,int code,const std::string& type,const std::string& body){
  std::ostringstream h;h<<"HTTP/1.1 "<<code<<(code==200?" OK":" Error")<<"\r\nContent-Type: "<<type<<"; charset=utf-8\r\nContent-Length: "<<body.size()<<"\r\nConnection: close\r\n\r\n"<<body;
  auto s=h.str();send(fd,s.data(),s.size(),0);
}
static std::string error(const std::string& e){return "{\"ok\":false,\"error\":\""+e+"\"}";}
static std::string move_error(int rc){
  switch(rc){
    case -1:return "运动参数无效";case -2:return "目标位置不可达（逆解失败）";
    case -3:return "检测到碰撞风险";case -4:return "轨迹执行失败";
    case -5:return "运动超时";case -6:return "运动被停止";
    case -7:return "目标超出关节限位";case -8:return "机械臂正在执行其他运动";
    default:return "运动失败 rc="+std::to_string(rc);
  }
}

int main(){
  std::ifstream f("/home/mememe/ArmApi/dashboard/dashboard.html");
  html.assign(std::istreambuf_iterator<char>(f),{}); if(html.empty()){std::cerr<<"dashboard.html missing\n";return 1;}
  onero_api::onero_config_t cfg{};
  std::strncpy(cfg.device,"/dev/ttyACM0",sizeof(cfg.device)-1);
  std::strncpy(cfg.robot_model,"a1_r",sizeof(cfg.robot_model)-1);
  std::strncpy(cfg.version,"A1",sizeof(cfg.version)-1);
  std::strncpy(cfg.mount_orientation,"horizontal",sizeof(cfg.mount_orientation)-1);
  onero_api::OneroArm arm(cfg);
  if(!arm.valid()||!arm.is_hardware_connected()||arm.enable_motors()!=0){std::cerr<<"arm init/enable failed\n";return 2;}
  int server=socket(AF_INET,SOCK_STREAM,0),yes=1;setsockopt(server,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof(yes));
  sockaddr_in a{};a.sin_family=AF_INET;a.sin_port=htons(8080);a.sin_addr.s_addr=INADDR_ANY;
  if(bind(server,(sockaddr*)&a,sizeof(a))<0||listen(server,8)<0){perror("listen");return 3;}
  std::cout<<"DASHBOARD_READY http://0.0.0.0:8080"<<std::endl;
  while(true){
    int c=accept(server,nullptr,nullptr);if(c<0)continue;char buf[8192]{};int n=recv(c,buf,sizeof(buf)-1,0);if(n<=0){close(c);continue;}
    std::istringstream r(std::string(buf,n));std::string method,path,ver;r>>method>>path>>ver;
    if(method=="GET"&&(path=="/"||path=="/index.html")){reply(c,200,"text/html",html);}
    else if(method=="GET"&&path.rfind("/api/state",0)==0){
      auto s=arm.get_arm_state_from_motor();if(s.positions.size()!=7)reply(c,500,"application/json",error("无法读取七关节状态"));
      else{std::ostringstream j;j<<"{\"ok\":true,\"positions\":[";for(int i=0;i<7;i++){if(i)j<<',';j<<s.positions[i];}j<<"]}";reply(c,200,"application/json",j.str());}
    } else if(method=="GET"&&path.rfind("/api/pose",0)==0){
      auto p=arm.get_end_effector_pose();
      std::ostringstream j;j<<"{\"ok\":true,\"pose\":{\"x\":"<<p.x<<",\"y\":"<<p.y<<",\"z\":"<<p.z<<",\"qw\":"<<p.qw<<",\"qx\":"<<p.qx<<",\"qy\":"<<p.qy<<",\"qz\":"<<p.qz<<"}}";
      reply(c,200,"application/json",j.str());
    } else if(method=="POST"&&path.rfind("/api/end-move",0)==0){
      auto q=query(path);double dx=0,dy=0,dz=0,speed=0;
      try{dx=std::stod(q.at("dx"));dy=std::stod(q.at("dy"));dz=std::stod(q.at("dz"));speed=std::stod(q.at("speed"));}catch(...){reply(c,400,"application/json",error("参数无效"));close(c);continue;}
      const double norm=std::sqrt(dx*dx+dy*dy+dz*dz);
      if(norm>.0801||speed<0.05||speed>0.20)reply(c,400,"application/json",error("末端位移超出 8 cm 安全限制"));
      else{
        auto start=arm.get_end_effector_pose();
        arm.reset_stop_signal();
        arm.clear_trajectory_buffer();
        const int segments=std::max(1,static_cast<int>(std::ceil(norm/.02)));
        int rc=0;
        for(int i=1;i<=segments&&rc==0;i++){
          const double t=static_cast<double>(i)/segments;auto p=start;
          p.x+=dx*t;p.y+=dy*t;p.z+=dz*t;
          rc=arm.movep(p,speed,segments>1?1:0);
        }
        if(rc){arm.clear_trajectory_buffer();reply(c,500,"application/json",error(move_error(rc)));}
        else if(segments>1&&(rc=arm.execute_buffered_trajectory())!=0){arm.clear_trajectory_buffer();reply(c,500,"application/json",error(move_error(rc)));}
        else reply(c,200,"application/json","{\"ok\":true,\"message\":\"末端平滑逆解完成（"+std::to_string(segments)+" 段）\"}");
      }
    } else if(method=="POST"&&path.rfind("/api/jog",0)==0){
      auto q=query(path);int joint=-1;double delta=0,speed=0;
      try{joint=std::stoi(q.at("joint"));delta=std::stod(q.at("delta"));speed=std::stod(q.at("speed"));}catch(...){reply(c,400,"application/json",error("参数无效"));close(c);continue;}
      if(joint<0||joint>6||std::abs(delta)>0.17454||speed<0.05||speed>0.25)reply(c,400,"application/json",error("参数超出安全限制"));
      else{auto s=arm.get_arm_state_from_motor();if(s.positions.size()!=7)reply(c,500,"application/json",error("状态读取失败"));else{s.positions[joint]+=delta;arm.reset_stop_signal();int rc=arm.movej(s.positions,speed,0);if(rc)reply(c,500,"application/json",error(rc==-6?"运动仍处于停止状态，请重试":"运动失败 rc="+std::to_string(rc)));else reply(c,200,"application/json","{\"ok\":true,\"message\":\"J"+std::to_string(joint+1)+" 步进完成\"}");}}
    } else if(method=="POST"&&path=="/api/tail"){
      auto s=arm.get_arm_state_from_motor();int rc=-1;if(s.positions.size()==7){arm.reset_stop_signal();auto center=s.positions,left=center,right=center;left[3]+=.10;left[5]-=.14;right[3]-=.10;right[5]+=.14;rc=0;for(int i=0;i<3&&rc==0;i++){rc=arm.movej(left,.15,1);if(!rc)rc=arm.movej(right,.15,1);}if(!rc)rc=arm.movej(center,.10,1);if(!rc)rc=arm.execute_buffered_trajectory();}
      if(rc)reply(c,500,"application/json",error("摇尾巴动作失败 rc="+std::to_string(rc)));else reply(c,200,"application/json","{\"ok\":true,\"message\":\"摇尾巴完成，已返回中心姿态\"}");
    } else if(method=="POST"&&path=="/api/extend-horizontal"){
      JointArray target(7,0.0);
      arm.reset_stop_signal();
      int rc=arm.movej(target,.08,0);
      if(rc)reply(c,500,"application/json",error("平举动作失败 rc="+std::to_string(rc)));
      else reply(c,200,"application/json","{\"ok\":true,\"message\":\"机械臂已从墙面向外水平伸直\"}");
    } else if(method=="POST"&&path=="/api/stop"){
      int rc=arm.cancel_trajectory();reply(c,rc?500:200,"application/json",rc?error("停止失败 rc="+std::to_string(rc)):"{\"ok\":true,\"message\":\"已请求停止当前轨迹；电机仍保持使能\"}");
    } else reply(c,404,"application/json",error("接口不存在"));
    close(c);
  }
}
