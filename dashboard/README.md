# 疯狂原始人 · Onero A1 示教与视觉控制

这部分代码为 Onero A1 机械臂提供：

- 零力拖动示教、轨迹录制与回放
- 自定义动作名称、独立动作库与删除功能
- 左右臂切换和设备序列号隔离
- 默认关闭、手动开启的三维末端 MoveP 控制
- 浏览器安全确认与停止入口
- reCamera 实时画面、物品检测和视觉闭环靠近
- 浏览器语音识别和动作库语音触发
- USB-CAN 唯一硬件 ID 自动发现、掉电恢复和健康检查

## 文件

- `a1r_teaching_server.cpp`：可通过环境变量配置左右臂的 HTTP/C++ 控制服务
- `teaching.html`：双臂动作库和三维末端控制页面
- `start_dual_a1_control.sh`：当前硬件的双臂启动脚本
- `a1r_dashboard_server.cpp`、`dashboard.html`：早期单臂控制面板，保留作参考
- `vision_approach.py`：视觉目标跟踪与靠近服务（端口 `8090`）
- `restart_all.sh`：板端控制与视觉服务一键重启
- `serial_watchdog.sh`：USB-CAN 掉线和重枚举自动恢复
- `crazy-caveman-watchdog.service`：看门狗 systemd 服务
- `recamera_detection_nodes.json`：reCamera Node-RED 检测流程
- `疯狂原始人_机器人系统技术说明.docx`：系统技术说明文档

## 依赖

板子需要安装 Onero ArmApi C++ SDK，并具有以下目录布局：

```text
/home/mememe/ArmApi/
├── c++/include/
├── c++/linux/linux-riscv64/liboneroarm.so
└── dashboard/
```

编译示例：

```bash
g++ -std=c++17 -O2 -pthread \
  -I/home/mememe/ArmApi/c++/include \
  dashboard/a1r_teaching_server.cpp \
  -L/home/mememe/ArmApi/c++/linux/linux-riscv64 -loneroarm \
  -Wl,-rpath,/home/mememe/ArmApi/c++/linux/linux-riscv64 \
  -o dashboard/a1r_teaching_server
```

## 启动

先根据实际 USB-CAN 序列号修改 `start_dual_a1_control.sh` 中的 `RIGHT_DEV` 和
`LEFT_DEV`，再执行：

```bash
chmod +x dashboard/start_dual_a1_control.sh
dashboard/start_dual_a1_control.sh
```

默认端口：右臂 `8080`，左臂 `8081`。浏览器访问板子 IP 的 `8080` 端口。

单臂视觉平台可直接执行：

```bash
chmod +x dashboard/restart_all.sh dashboard/serial_watchdog.sh
dashboard/restart_all.sh
```

安装自动串口恢复服务：

```bash
sudo cp dashboard/crazy-caveman-watchdog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crazy-caveman-watchdog.service
```

服务默认通过 `/dev/serial/by-id/*CANable*` 识别 USB-CAN，因此重新上电后即使
内核设备名从 `ttyACM0` 变为 `ttyACM1`，也会选择同一个硬件。

## 安全

机械臂无自动避障且无抱闸。录制、回放和三维控制前必须确认安装牢固、零点正确、
工作区无人无障碍并准备急停。三维末端控制默认关闭。
