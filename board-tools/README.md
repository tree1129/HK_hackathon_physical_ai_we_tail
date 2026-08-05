# K3 板端调试工具

本目录是从实际运行的 K3 板 `/home/mememe/ArmApi/demo/cpp/` 原样导出的项目调试源码。

- `a1r_read_state.cpp`：读取 7 个关节的位置、速度和力矩，不使能电机
- `a1r_enable_hold.cpp`：使能电机并保持控制会话
- `a1r_j4_low_speed_test.cpp`：J4 小幅低速往返测试
- `a1r_tail_wag.cpp`：J4/J6 联动的三周期摇尾动作测试

## K3 板端编译

在 `/home/mememe/ArmApi` 下执行（将 `<name>` 替换为文件名）：

```bash
g++ -std=c++17 -O2 -pthread \
  -I./c++/include \
  board-tools/<name>.cpp \
  -L./c++/linux/linux-riscv64 -loneroarm \
  -Wl,-rpath,/home/mememe/ArmApi/c++/linux/linux-riscv64 \
  -o demo/build/<name>
```

## 注意

这些程序会直接访问机械臂。运行运动测试前必须停止 dashboard 控制服务，避免多个
进程同时占用 USB-CAN；确认机械臂固定、工作区无人无障碍并准备急停。
