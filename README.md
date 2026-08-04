# HK Hackathon Physical AI: Arm + Tailhand

本分支汇总机械臂控制与 LinkerHand O6 灵巧手控制，便于双端并行开发和后续联调。

## 项目目录

- `dashboard/`：Onero A1L/A1R 双臂示教、轨迹回放和网页控制，由机械臂控制进程负责。
- `tailhand/`：LinkerHand O6 左/右手基础驱动、Mac 摄像头手势跟随、reCamera 腕部视觉自动抓取、iPhone LiDAR 实验链路和网页控制台。

详细启动说明分别见 [dashboard/README.md](dashboard/README.md) 和 [tailhand/README.md](tailhand/README.md)。

## 推荐联调边界

首轮联调保持两个独立控制进程：

1. 机械臂进程只控制手臂和手腕位姿。
2. `tailhand/apps/o6-camera-teleop` 只控制 O6 六个手指通道。
3. reCamera 画面由 Mac 读取并完成目标检测；点击 `布防识别` 后，中央目标稳定 8 帧才允许限速握合。
4. O6 抓取完成后保持姿态；释放必须点击 `安全张开`。

不要让多个程序同时向同一 CAN 设备写指令。机械臂与 O6 联调前应固定设备、清空运动范围，并保留物理断电手段。

## O6 快速启动

在 macOS Terminal 中执行：

```bash
cd tailhand/apps/o6-camera-teleop
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run_web.sh --dry-run --port 8765
```

浏览器打开 `http://127.0.0.1:8765`。完成模拟验证后停止进程，再运行：

```bash
./run_web.sh --real --port 8765
```

真机模式必须确认网页显示 `mac-pcan-o6`、硬件已连接和正确的左/右手地址后再布防。
