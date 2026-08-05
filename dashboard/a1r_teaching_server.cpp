#include "onero_interface_cpp.h"
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;
using onero_api::OneroArm;
using onero_api::OneroDragTeaching;

static const fs::path library_dir = "/home/mememe/ArmApi/trajectory_library";
static const fs::path working_file = "trajectory_library/recording.dat";
static const std::string device_path = [] {
  const char *configured = std::getenv("A1R_DEVICE");
  return std::string(configured && *configured ? configured : "/dev/ttyACM0");
}();
static std::string html, recording_name;
static std::unique_ptr<OneroArm> arm;
static std::shared_ptr<OneroDragTeaching> teaching;
static std::mutex controller_mutex;

static std::string json_escape(const std::string &s) {
  std::ostringstream o;
  for (unsigned char c : s) {
    if (c == '"' || c == '\\') o << '\\' << c;
    else if (c < 0x20) o << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c);
    else o << c;
  }
  return o.str();
}

static int hexval(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static std::string url_decode(const std::string &s) {
  std::string out;
  for (size_t i = 0; i < s.size(); ++i) {
    if (s[i] == '%' && i + 2 < s.size() && hexval(s[i+1]) >= 0 && hexval(s[i+2]) >= 0) {
      out.push_back(char(hexval(s[i+1]) * 16 + hexval(s[i+2]))); i += 2;
    } else out.push_back(s[i] == '+' ? ' ' : s[i]);
  }
  return out;
}

static std::string param(const std::string &path, const std::string &key) {
  auto p = path.find('?'); if (p == std::string::npos) return {};
  std::stringstream ss(path.substr(p + 1)); std::string item;
  while (std::getline(ss, item, '&')) {
    auto e = item.find('=');
    if (e != std::string::npos && item.substr(0, e) == key) return url_decode(item.substr(e + 1));
  }
  return {};
}

static void reply(int fd, int code, const std::string &type, const std::string &body) {
  std::ostringstream h; h << "HTTP/1.1 " << code << (code == 200 ? " OK" : " Error")
    << "\r\nContent-Type: " << type << "; charset=utf-8\r\nContent-Length: " << body.size()
    << "\r\nConnection: close\r\n\r\n" << body;
  auto s = h.str(); send(fd, s.data(), s.size(), 0);
}
static std::string fail(const std::string &s) { return "{\"ok\":false,\"error\":\"" + json_escape(s) + "\"}"; }
static std::string move_error(int rc) {
  switch (rc) {
    case -1: return "运动参数无效"; case -2: return "目标位置不可达（逆解失败）";
    case -3: return "检测到碰撞风险"; case -4: return "轨迹执行失败";
    case -5: return "运动超时"; case -6: return "运动被停止";
    case -7: return "目标超出关节限位"; case -8: return "机械臂正在执行其他运动";
    default: return "运动失败 rc=" + std::to_string(rc);
  }
}

static bool safe_id(const std::string &id) {
  if (id.empty() || id.size() > 32 || id == "recording") return false;
  for (unsigned char c : id)
    if (!(std::isalnum(c) || c == '-' || c == '_')) return false;
  return true;
}

static std::string new_id() {
  auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
  std::string id = std::to_string(ms);
  while (fs::exists(library_dir / (id + ".dat"))) id += "0";
  return id;
}

static bool ensure_arm(std::string &err) {
  if (arm) return true;
  if (teaching) {
    teaching->handle_command(0); teaching.reset();
    std::this_thread::sleep_for(std::chrono::milliseconds(700));
  }
  onero_api::onero_config_t cfg{};
  std::strncpy(cfg.device, device_path.c_str(), sizeof(cfg.device)-1);
  std::strncpy(cfg.robot_model, "a1_r", sizeof(cfg.robot_model)-1);
  std::strncpy(cfg.version, "A1", sizeof(cfg.version)-1);
  std::strncpy(cfg.mount_orientation, "horizontal", sizeof(cfg.mount_orientation)-1);
  arm = std::make_unique<OneroArm>(cfg);
  if (!arm->valid() || !arm->is_hardware_connected() || arm->enable_motors() != 0) {
    arm.reset(); err = "位置控制器初始化失败"; return false;
  }
  // Merely enabling the motors after zero-force teaching does not hold the
  // current configuration.  Lock the measured pose immediately so the arm
  // cannot sag while the UI or vision loop waits for its first command.
  std::this_thread::sleep_for(std::chrono::milliseconds(120));
  auto hold_pose = arm->get_end_effector_pose();
  arm->reset_stop_signal();
  if (arm->movep(hold_pose, 0.05, 0) != 0) {
    arm->disable_motors(); arm.reset(); err = "当前位置保持失败"; return false;
  }
  return true;
}

static bool ensure_teaching(std::string &err) {
  if (teaching) return true;
  if (arm) {
    arm->cancel_trajectory(); arm->disable_motors(); arm.reset();
    std::this_thread::sleep_for(std::chrono::milliseconds(700));
  }
  teaching = std::make_shared<OneroDragTeaching>();
  if (!teaching->valid() || !teaching->initialize(7, working_file.string(), 0.01) ||
      !teaching->set_hardware(device_path, "", "a1_r", "horizontal")) {
    teaching.reset(); err = "示教控制器初始化失败"; return false;
  }
  return true;
}

static std::string action_list_json() {
  std::ostringstream j; j << '['; bool first = true;
  if (fs::exists(library_dir)) for (const auto &e : fs::directory_iterator(library_dir)) {
    if (!e.is_regular_file() || e.path().extension() != ".dat" || e.path().filename() == "recording.dat") continue;
    auto id = e.path().stem().string(); if (!safe_id(id)) continue;
    std::ifstream nf(library_dir / (id + ".name")); std::string name; std::getline(nf, name);
    if (name.empty()) {
      if (id == "sit") name = "坐下";
      else if (id == "wave") name = "招手";
      else if (id == "pick") name = "拿东西";
      else name = id;
    }
    if (!first) j << ','; first = false;
    j << "{\"id\":\"" << id << "\",\"name\":\"" << json_escape(name) << "\"}";
  }
  j << ']'; return j.str();
}

int main() {
  fs::create_directories(library_dir);
  std::ifstream f("/home/mememe/ArmApi/dashboard/teaching.html");
  html.assign(std::istreambuf_iterator<char>(f), {}); if (html.empty()) return 1;
  std::string init_error;
  // Start unlocked in zero-force teaching mode. Position holding is acquired
  // lazily by pose/jog/move requests through ensure_arm().
  { std::lock_guard<std::mutex> lk(controller_mutex); if (!ensure_teaching(init_error)) { std::cerr << init_error << '\n'; return 2; } }

  std::atomic<bool> running{true};
  std::thread tick([&] { auto next = std::chrono::steady_clock::now(); while (running) {
    std::shared_ptr<OneroDragTeaching> active_teaching;
    { std::lock_guard<std::mutex> lk(controller_mutex); active_teaching = teaching; }
    if (active_teaching) active_teaching->timer_callback();
    next += std::chrono::milliseconds(10); std::this_thread::sleep_until(next);
  }});

  int server = socket(AF_INET, SOCK_STREAM, 0), yes = 1; setsockopt(server,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof(yes));
  sockaddr_in a{}; a.sin_family=AF_INET; a.sin_port=htons(8080); a.sin_addr.s_addr=INADDR_ANY;
  if (bind(server,(sockaddr*)&a,sizeof(a))<0 || listen(server,8)<0) { perror("listen"); return 3; }
  std::cout << "TEACHING_LIBRARY_READY http://0.0.0.0:8080\n" << std::flush;

  while (running.load()) {
    int c=accept(server,nullptr,nullptr); if(c<0)continue; char buf[8192]{}; int n=recv(c,buf,sizeof(buf)-1,0); if(n<=0){close(c);continue;}
    std::istringstream r(std::string(buf,n)); std::string method,path,ver; r>>method>>path>>ver;
    if(method=="GET"&&(path=="/"||path=="/index.html")) reply(c,200,"text/html",html);
    else if(method=="GET"&&path.rfind("/api/status",0)==0) {
      std::lock_guard<std::mutex> lk(controller_mutex);
      const bool replaying = teaching && teaching->get_state() == onero_api::DragTeachingState::REPLAYING;
      reply(c,200,"application/json","{\"ok\":true,\"mode\":\""+std::string(teaching?"teaching":"position")+"\",\"recording\":"+(recording_name.empty()?"false":"true")+",\"replaying\":"+(replaying?"true":"false")+",\"actions\":"+action_list_json()+"}");
    } else if(method=="GET"&&path.rfind("/api/joints",0)==0) {
      std::lock_guard<std::mutex> lk(controller_mutex);std::string err;
      if(teaching) reply(c,409,"application/json",fail("示教模式下暂停关节状态轮询"));
      else if(!recording_name.empty()) reply(c,409,"application/json",fail("录制中不能切换关节控制"));
      else if(!ensure_arm(err)) reply(c,500,"application/json",fail(err));
      else {auto s=arm->get_arm_state_from_motor();if(s.positions.size()!=7)reply(c,500,"application/json",fail("无法读取七关节状态"));else{std::ostringstream j;j<<"{\"ok\":true,\"positions\":[";for(int i=0;i<7;i++){if(i)j<<',';j<<s.positions[i];}j<<"]}";reply(c,200,"application/json",j.str());}}
    } else if(method=="GET"&&path.rfind("/api/pose",0)==0) {
      std::lock_guard<std::mutex> lk(controller_mutex); std::string err;
      if(teaching) reply(c,409,"application/json",fail("示教模式下暂停末端状态轮询"));
      else if(!recording_name.empty()) reply(c,409,"application/json",fail("录制中不能切换到三维控制"));
      else if(!ensure_arm(err)) reply(c,500,"application/json",fail(err));
      else { auto p=arm->get_end_effector_pose(); std::ostringstream j; j<<"{\"ok\":true,\"pose\":{\"x\":"<<p.x<<",\"y\":"<<p.y<<",\"z\":"<<p.z<<",\"qw\":"<<p.qw<<",\"qx\":"<<p.qx<<",\"qy\":"<<p.qy<<",\"qz\":"<<p.qz<<"}}"; reply(c,200,"application/json",j.str()); }
    } else if(method=="POST"&&path.rfind("/api/end-move",0)==0) {
      double dx,dy,dz,speed; try{dx=std::stod(param(path,"dx"));dy=std::stod(param(path,"dy"));dz=std::stod(param(path,"dz"));speed=std::stod(param(path,"speed"));}catch(...){reply(c,400,"application/json",fail("参数无效"));close(c);continue;}
      double norm=std::sqrt(dx*dx+dy*dy+dz*dz); std::lock_guard<std::mutex> lk(controller_mutex); std::string err;
      if(norm>.0801||speed<.05||speed>.20) reply(c,400,"application/json",fail("末端位移超出 8 cm 安全限制"));
      else if(teaching && teaching->get_state() == onero_api::DragTeachingState::REPLAYING) reply(c,409,"application/json",fail("回放中不能执行末端运动"));
      else if(!recording_name.empty()) reply(c,409,"application/json",fail("录制中不能执行末端运动"));
      else if(!ensure_arm(err)) reply(c,500,"application/json",fail(err));
      else {
        auto start=arm->get_end_effector_pose();arm->reset_stop_signal();arm->clear_trajectory_buffer();
        const int segments=std::max(1,static_cast<int>(std::ceil(norm/.02)));int rc=0;
        for(int i=1;i<=segments&&rc==0;i++){
          const double t=static_cast<double>(i)/segments;auto p=start;
          p.x+=dx*t;p.y+=dy*t;p.z+=dz*t;rc=arm->movep(p,speed,segments>1?1:0);
        }
        if(rc){arm->clear_trajectory_buffer();reply(c,500,"application/json",fail(move_error(rc)));}
        else if(segments>1&&(rc=arm->execute_buffered_trajectory())!=0){arm->clear_trajectory_buffer();reply(c,500,"application/json",fail(move_error(rc)));}
        else reply(c,200,"application/json","{\"ok\":true,\"message\":\"末端平滑逆解完成（"+std::to_string(segments)+" 段）\"}");
      }
    } else if(method=="POST"&&path.rfind("/api/jog",0)==0) {
      int joint;double delta,speed;try{joint=std::stoi(param(path,"joint"));delta=std::stod(param(path,"delta"));speed=std::stod(param(path,"speed"));}catch(...){reply(c,400,"application/json",fail("关节参数无效"));close(c);continue;}
      static const double lower[7]={-1.04,-3.14,-2.75,-1.92,-2.75,-1.57,-2.75};
      static const double upper[7]={ 3.14, 0.26, 2.75, 1.92, 2.75, 1.57, 2.75};
      std::lock_guard<std::mutex> lk(controller_mutex);std::string err;
      if(joint<0||joint>6||std::abs(delta)>.17454||speed<.05||speed>.25) reply(c,400,"application/json",fail("关节运动参数超出安全限制"));
      else if(teaching&&teaching->get_state()==onero_api::DragTeachingState::REPLAYING) reply(c,409,"application/json",fail("回放中不能控制关节"));
      else if(!recording_name.empty()) reply(c,409,"application/json",fail("录制中不能控制关节"));
      else if(!ensure_arm(err)) reply(c,500,"application/json",fail(err));
      else {auto s=arm->get_arm_state_from_motor();if(s.positions.size()!=7)reply(c,500,"application/json",fail("无法读取关节状态"));else{const double target=s.positions[joint]+delta;if(target<lower[joint]||target>upper[joint])reply(c,400,"application/json",fail("J"+std::to_string(joint+1)+" 将超出关节限位"));else{s.positions[joint]=target;arm->reset_stop_signal();int rc=arm->movej(s.positions,speed,0);reply(c,rc?500:200,"application/json",rc?fail(move_error(rc)):"{\"ok\":true,\"message\":\"J"+std::to_string(joint+1)+" 运动完成\"}");}}}
    } else if(method=="POST"&&path=="/api/teaching/enable") {
      std::lock_guard<std::mutex> lk(controller_mutex); std::string err;
      if(!recording_name.empty()) reply(c,409,"application/json",fail("已有动作正在录制"));
      else if(!ensure_teaching(err)) reply(c,500,"application/json",fail(err));
      else reply(c,200,"application/json","{\"ok\":true,\"message\":\"已进入零力示教待命\"}");
    } else if(method=="POST"&&path.rfind("/api/record/start",0)==0) {
      auto name=param(path,"name"); if(name.empty()||name.size()>80) reply(c,400,"application/json",fail("动作名称不能为空且最多 80 字节"));
      else {std::lock_guard<std::mutex> lk(controller_mutex);std::string err;if(!recording_name.empty())reply(c,409,"application/json",fail("已有动作正在录制"));else if(!ensure_teaching(err))reply(c,500,"application/json",fail(err));else{std::error_code ec;fs::remove(working_file,ec);int rc=teaching->handle_command(1);if(rc)reply(c,500,"application/json",fail("进入零力录制失败 rc="+std::to_string(rc)));else{recording_name=name;reply(c,200,"application/json","{\"ok\":true,\"message\":\"已进入零力录制\"}");}}}
    } else if(method=="POST"&&path=="/api/record/stop") {
      std::lock_guard<std::mutex> lk(controller_mutex);if(recording_name.empty())reply(c,409,"application/json",fail("当前没有录制"));else{int rc=teaching->handle_command(2);if(rc)reply(c,500,"application/json",fail("停止录制失败"));else{auto id=new_id();std::error_code ec;fs::copy_file(working_file,library_dir/(id+".dat"),fs::copy_options::none,ec);if(ec)reply(c,500,"application/json",fail("保存失败，原动作未被覆盖"));else{std::ofstream(library_dir/(id+".name"))<<recording_name<<'\n';recording_name.clear();reply(c,200,"application/json","{\"ok\":true,\"message\":\"已作为新动作保存\"}");}}}
    } else if(method=="POST"&&path.rfind("/api/play",0)==0) {
      auto id=param(path,"id");std::lock_guard<std::mutex> lk(controller_mutex);std::string err;if(!safe_id(id)||!fs::exists(library_dir/(id+".dat")))reply(c,404,"application/json",fail("动作不存在"));else if(!recording_name.empty())reply(c,409,"application/json",fail("请先停止录制"));else if(!ensure_teaching(err))reply(c,500,"application/json",fail(err));else{teaching->set_replay_file((fs::path("trajectory_library")/(id+".dat")).string());int rc=teaching->handle_command(3);reply(c,rc?500:200,"application/json",rc?fail("回放失败 rc="+std::to_string(rc)):"{\"ok\":true,\"message\":\"动作回放已启动\"}");}
    } else if(method=="POST"&&path.rfind("/api/delete",0)==0) {
      auto id=param(path,"id");std::lock_guard<std::mutex> lk(controller_mutex);if(!safe_id(id))reply(c,400,"application/json",fail("动作编号无效"));else{std::error_code e1,e2;bool removed=fs::remove(library_dir/(id+".dat"),e1);fs::remove(library_dir/(id+".name"),e2);reply(c,removed&& !e1?200:404,"application/json",removed&&!e1?"{\"ok\":true,\"message\":\"动作已删除\"}":fail("动作不存在或删除失败"));}
    } else if(method=="POST"&&path=="/api/stop") {
      std::lock_guard<std::mutex> lk(controller_mutex);int rc=teaching?teaching->handle_command(0):(arm?arm->cancel_trajectory():0);recording_name.clear();reply(c,rc?500:200,"application/json",rc?fail("停止失败"):"{\"ok\":true,\"message\":\"已请求停止\"}");
    } else if(method=="POST"&&path=="/api/shutdown") {
      {
        std::lock_guard<std::mutex> lk(controller_mutex);
        if(teaching) teaching->handle_command(0);
        if(arm) { arm->cancel_trajectory(); arm->disable_motors(); }
        recording_name.clear();
      }
      reply(c,200,"application/json","{\"ok\":true,\"message\":\"控制服务正在安全退出\"}");
      running.store(false);
    } else reply(c,404,"application/json",fail("接口不存在"));
    close(c);
  }
  running.store(false);
  if(tick.joinable()) tick.join();
  {
    std::lock_guard<std::mutex> lk(controller_mutex);
    if(teaching) { teaching->handle_command(0); teaching.reset(); }
    if(arm) { arm->cancel_trajectory(); arm->disable_motors(); arm.reset(); }
  }
  close(server);
  return 0;
}
