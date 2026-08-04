# Onero A1 双臂示教与可视化控制

这部分代码为 Onero A1L/A1R 双臂提供：

- 零力拖动示教、轨迹录制与回放
- 自定义动作名称、独立动作库与删除功能
- 左右臂切换和设备序列号隔离
- 默认关闭、手动开启的三维末端 MoveP 控制
- 浏览器安全确认与停止入口

## 文件

- `a1r_teaching_server.cpp`：可通过环境变量配置左右臂的 HTTP/C++ 控制服务
- `teaching.html`：双臂动作库和三维末端控制页面
- `start_dual_a1_control.sh`：当前硬件的双臂启动脚本
- `a1r_dashboard_server.cpp`、`dashboard.html`：早期单臂控制面板，保留作参考

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

## 安全

机械臂无自动避障且无抱闸。录制、回放和三维控制前必须确认安装牢固、零点正确、
工作区无人无障碍并准备急停。三维末端控制默认关闭。
