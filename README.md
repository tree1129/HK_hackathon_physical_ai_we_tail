# Tailhand: LinkerHand O6 on macOS

这个仓库汇总灵心巧手 LinkerHand O6 的基础驱动、Mac 摄像头手势映射、物品自动抓取、网页可视化控制台、实机数据和排障记录。

> 型号记录：最初对话曾把设备称为 L6，随后已明确更正为 **O6**。当前连接设备为 **O6 左手**，CAN ID `0x28`。

## 目录

- `apps/o6-camera-teleop/`：当前主项目。单一运行器、一个摄像头和一个 CAN 控制器，网页提供手势跟随与物品抓取两种互斥模式，并可切换左手/右手设备。
- `archive/o6-basic-driver/`：早期稳定的终端基础驱动，包含张开、握拳、数字手势、单指、循环张合和四指波浪动作。
- `docs/PROJECT_HISTORY.md`：需求演进、关键决策、已解决问题和剩余边界。
- `docs/HARDWARE_NOTES.md`：SDK API、CAN 协议、当前实测值和平台差异。
- `docs/COMMAND_REFERENCE.md`：日常运行命令与安全操作顺序。

官方 Python SDK 以 Git 子模块固定在已核对的提交 `fbec1057`。首次克隆必须带子模块：

```bash
git clone --recurse-submodules https://github.com/Duamixu1/tailhand.git
cd tailhand/apps/o6-camera-teleop
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

先以模拟模式打开网页：

```bash
./run_web.sh --camera 0 --dry-run
```

访问 `http://127.0.0.1:8765`。确认摄像头、骨架、六维值和安全状态后再连接真机：

```bash
./run_web.sh --camera 0 --real
```

真机连接成功的必要标志：页面同时显示 `真机模式`、后端 `mac-pcan-o6`、硬件 `已连接`。`dry-run` 或 `dry-run-fallback` 都不会控制硬件。

## 当前验收状态

- Mac 自带摄像头索引 `0` 已运行 MediaPipe 21 点手部识别。
- 当前 O6 左手在 `PCAN_USBBUS1 @ 1 Mbps` 上通过 `0x28` 连续返回 6 维状态。
- 网页真机启动已验证 `backend=mac-pcan-o6`、`connected=true`、默认物品模式 `DISARMED`、0 条自动动作指令。
- 手势跟随必须二次点击启用；丢手超过 0.5 秒停止下发。
- 物品抓取必须先布防，且检测到人手进入抓取区时禁止闭合。

软件急停不能替代物理断电。首次动作前固定机械手，清空运动范围，并关闭其他可能写入同一 CAN 总线的程序。

