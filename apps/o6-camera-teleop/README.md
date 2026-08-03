# LinkerHand O6 Camera Teleop

普通摄像头实时识别人手 21 个关键点，将手指几何姿态映射为灵心巧手 O6 的 6 个控制量，并经过 EMA、死区、单次变化限幅和发送频率限制后驱动真机。

项目还提供安全的物品抓取模式：检测进入指定区域的新物品，在确认人的手已经离开后，让固定位置的 O6 自动闭合。O6 本身没有机械臂，因此不会移动手掌去接近远处物品；物品必须已经放在 O6 掌心和摄像头绿色抓取区内。

控制顺序固定为：

```python
[
    "thumb_flexion",
    "thumb_abduction",
    "index_flexion",
    "middle_flexion",
    "ring_flexion",
    "pinky_flexion",
]
```

## macOS 快速启动

这里的 `--camera 0` 是 **Mac 自带摄像头**。本机枚举到的 iPhone 连续互通摄像头是索引 1，本项目不会默认使用它。

```bash
cd tailhand/apps/o6-camera-teleop
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

### 推荐：打开本地网页控制台

在 macOS 的 Terminal 中执行：

```bash
cd tailhand/apps/o6-camera-teleop
./run_web.sh --camera 0 --dry-run
```

终端出现 `O6 visual console: http://127.0.0.1:8765` 后，用 Safari 或 Chrome 打开：

```text
http://127.0.0.1:8765
```

网页直接显示 Mac 摄像头、21 点手骨架、物品框、识别状态、O6 六维值和真实后端。一个运行器提供两个互斥模式：

- `手势跟随`：先切换模式，再点击 `启用跟随`。未启用时只显示识别预览，不会驱动 O6；点击 `暂停跟随` 后保持最后姿态。
- `物品抓取`：先清空绿色区域，再点击 `布防识别` 记录背景；放入物品并将人手移开后才会自动闭合。

切换模式会先发送安全张开并清空上一模式的状态。`安全张开` 和 `紧急停止` 在两种模式中始终可用；急停锁存后必须重启运行器才能重新启用动作。默认 `--dry-run` 不连接硬件；确认画面、模式切换和安全门禁正确后，按 `Ctrl-C` 停止，再启动真机：

```bash
./run_web.sh --camera 0 --real
```

完整项目目录可在 Finder 中打开：

```bash
open .
```

也可在 VS Code 中打开（已安装 `code` 命令时）：

```bash
code .
```

网页服务器只绑定 `127.0.0.1`，局域网其他设备默认不能访问。关闭网页不会结束机器人进程；回到启动它的 Terminal 按 `Ctrl-C` 才会安全停止，真机连接正常且未急停时会先发送安全张开。

先看识别和映射，不碰硬件：

```bash
.venv/bin/python app.py --camera 0 --dry-run
```

连接当前 O6 左手真机：

```bash
.venv/bin/python app.py --camera 0 --real
```

也可以使用包装脚本：

```bash
./run_mac.sh --camera 0 --real
```

`app.py` 会在 macOS 自动重新加载随包的 MacCAN PCBUSB 动态库，所以直接执行 Python 命令也可以。MacCAN 文件和许可证位于 `third_party/maccan/`。

## 网页双模式操作

页面中的 `O6 设备` 可在 `左手 / 右手` 间切换。左手使用 CAN ID `0x28`，右手使用 `0x27`。切换时运行器会暂停跟随、清除抓取状态、释放当前 CAN 连接，再按新地址重连并发送安全张开；真机无响应时会明确显示回退模拟。

### 手势跟随

1. 确认顶部显示 `真机模式`，诊断中的后端为 `mac-pcan-o6`、硬件连接为 `已连接`。
2. 点击 `手势跟随`。O6 会先安全张开，但此时只显示骨架和六维映射预览。
3. 将手完整放入画面，确认页面显示左右手和识别置信度。
4. 点击 `启用跟随`，O6 才开始同步运动。
5. 点击 `暂停跟随`可停止继续下发；丢手超过 0.5 秒也会自动停止下发。

### 物品自动抓取

先运行 dry-run：

```bash
.venv/bin/python app.py --mode object-grasp --camera 0 --dry-run
```

操作顺序：

1. 清空画面中的绿色抓取框，确保 O6 已固定，物品不会跌落或夹伤人。
2. 按 `G`。程序记录当前空区域作为背景并进入 `ARMED`。
3. 把物品放入 O6 掌心和绿色框，然后把人的手完全移出绿色框。
4. 新物品稳定 8 次检测后，状态进入 `CLOSING`，O6 按限速闭合。
5. 到达抓取姿态后显示 `HOLDING`，不会因物品暂时识别丢失而自动松开。
6. 按 `O` 张开并复位；再次抓取需要重新按 `G`。

确认 dry-run 的框选与稳定计数正确后再运行真机：

```bash
.venv/bin/python app.py --mode object-grasp --camera 0 --real
```

物品模式同时使用三层判断：

- EfficientDet-Lite0 为 COCO 常见物品提供类别和置信度。
- 背景差分检测任何新放入的普通物品，未被 COCO 分类也显示为 `generic-object`。
- Hand Landmarker 检查抓取区；只要人的任一手部关键点在区域内，就显示 `HAND IN ZONE - BLOCKED`，清零稳定计数并禁止闭合。

默认抓取姿态 `[110,35,55,55,55,55]` 比完全握拳保守，可在 `config.yaml > object_grasp > grasp_pose` 修改。物品大小、刚度未知时不要直接使用 `[102,18,0,0,0,0]`；本模式尚未用 O6 触觉反馈构成夹持力闭环。

| 键 | 物品模式行为 |
| --- | --- |
| `G` | 在 DISARMED/ARMED 间切换；布防时重新采集背景 |
| `O` | 安全张开，清除目标并恢复 DISARMED |
| `E` | 紧急停止后续动作下发 |
| `Q` | 安全张开并退出 |

## OpenCV 可视窗口

- 绿色线条和黄色点：MediaPipe 的 21 个手部关键点。
- `TRACKING Left/Right`：当前检测状态、左右手和置信度。
- 每个通道显示 `human 0.00-1.00 -> O6 0-255` 及进度条。
- `backend`：实际后端。只有 `mac-pcan-o6` 或 `official-linkerhand-sdk` 才是真机；`dry-run-fallback` 明确表示硬件未连接。
- `HAND LOST - HOLDING`：短暂丢手，保持最后姿态。
- `HAND LOST - OUTPUT PAUSED`：连续丢手超过 0.5 秒，停止下发。

显示镜像仅影响观看，MediaPipe 和几何映射始终使用未镜像的原始坐标，因此不会因自拍镜像把控制方向反转。

## 标定和安全键

1. 自然完全张开手，按 `1` 记录张开样本。
2. 握拳，按 `2` 记录握拳样本。
3. 按 `S` 写入当前 `config.yaml`。

其他按键：

| 键 | 行为 |
| --- | --- |
| `R` | 清除几何标定并恢复默认映射；再按 `S` 才持久化 |
| `E` | 紧急锁存停止，不再发送跟随动作 |
| `O` | 明确发送配置中的安全张开姿态；不会解除紧急停止锁存 |
| `Q` | 安全退出；未急停时先张开，再释放 CAN 和摄像头 |

启动默认 `dry_run: true`。只有显式使用 `--real` 且后端连接成功，程序才会发送真机指令。

## 映射和安全机制

- 四指分别计算 MCP、PIP、DIP 三个 3D 关节弯曲角，融合为 `0.0-1.0`。
- 拇指分别计算屈曲和相对手掌/食指掌骨的外展角。
- 优先使用 MediaPipe 世界坐标，不使用手在画面中的绝对位置或像素尺寸。
- O6 的开/闭端点全部在 `config.yaml > o6 > channels` 中配置，代码不假设控制方向。
- 当前左手实测初值为张开约 `[250,250,250,250,250,250]`，握拳约 `[102,18,0,0,0,0]`。
- 默认 20 Hz，EMA `0.25`，死区 3，每次命令最大变化 12，所有值裁剪到 `0-255`。
- 检测丢失先保持最后姿态，超过 500 ms 停止发送，不生成猜测动作。

参数示例：

```bash
.venv/bin/python app.py --dry-run
.venv/bin/python app.py --camera 0 --dry-run
.venv/bin/python app.py --camera 0 --real
.venv/bin/python app.py --config config.yaml
.venv/bin/python app.py --mode object-grasp --camera 0 --dry-run
.venv/bin/python app.py --mode object-grasp --camera 0 --real
```

`--headless --max-frames N` 仅用于自动验证，不显示窗口。

## 官方 SDK 核对结果

项目固定了克隆快照 `fbec1057e5320918f634fff103835d9aaa0a2269`，没有修改其源码。实际代码核对结果：

- 导入：`from LinkerHand.linker_hand_api import LinkerHandApi`
- 初始化：`LinkerHandApi(hand_type="left|right", hand_joint="O6", modbus="None|串口", can="can0|PCAN_USBBUS1")`
- O6 左手 CAN ID `0x28`，右手 `0x27`。
- `finger_move(pose=pose)` 要求正好 6 个 `0-255` 值。
- `set_speed(speed=values)` 的 O6 底层要求正好 6 个值。
- `get_state()` 调用 O6 底层 `get_current_status()`。
- 实际配置文件是 `LinkerHand/config/setting.yaml`，不是仓库根目录的 `config/setting.yaml`。

已发现的上游差异/缺陷：

- 官方 O6 CAN 后端只实现 Linux `socketcan` 和 Windows `pcan/candle`，`darwin` 会抛出 `Unsupported platform for CAN interface`。因此本项目在 macOS CAN 上使用同一 O6 帧协议的本地 `python-can + MacCAN` 适配层；RS485、Linux 和 Windows 仍走官方 `LinkerHandApi`。
- 上游 `LinkerHandApi.close_can()` 引用了未绑定的 `modbus` 变量。本项目关闭时直接调用底层 `close_can_interface()`、串口 `close()` 或总线 `shutdown()`，不修改上游源码。
- 上游完整 `requirements.txt` 包含与 O6 运行无关的 `dm_control/MuJoCo/PyQt5/pyagxrobots`。本机已实际执行安装，但 Python 3.9 下的 MuJoCo 源码构建因缺少 `MUJOCO_PATH` 失败。项目 `requirements.txt` 已安装并包含 O6 CAN/RS485 真正使用的运行依赖，摄像与真机链路不依赖 MuJoCo。

## Ubuntu CAN

将 `config.yaml` 改为：

```yaml
o6:
  backend: auto
  can_channel: can0
  modbus: "None"
```

配置 1 Mbps SocketCAN：

```bash
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
ip -details link show can0
```

然后执行：

```bash
.venv/bin/python app.py --camera 0 --real
```

不要同时运行 ROS SDK、官方 GUI 或其他会向同一只手发送 CAN 帧的程序。

## RS485

O6 官方 SDK 的 RS485 固定使用 115200 baud。将端口写入配置即可绕过 CAN：

```yaml
o6:
  modbus: "/dev/ttyUSB0"  # Linux
  # modbus: "/dev/cu.usbserial-XXXX"  # macOS
```

Linux 临时授权：

```bash
sudo chmod 666 /dev/ttyUSB0
```

更稳定的部署应写 udev 规则，而不是长期 `chmod 777`。用 `ls /dev/ttyUSB* /dev/ttyACM*` 或 macOS 的 `ls /dev/cu.*` 确认真实端口。

## Windows

MediaPipe、OpenCV 摄像头和 dry-run 可用。官方 O6 CAN 源码优先使用 PEAK PCAN (`PCAN_USBBUS1`)，失败后尝试 candle；需要安装对应厂商驱动，并在 `config.yaml` 设置实际通道。Windows 未在本次 Mac 开发环境实机验证。

## 测试

最小测试覆盖输出长度/范围、开闭方向、EMA、单次最大变化、抓取状态机、通用前景检测和网页控制接口：

```bash
.venv/bin/python -m unittest tests/test_mapper.py
```

本机验收记录：

- MacBook Air Camera (`--camera 0`) 已连续处理 30 帧 dry-run，退出码 0。
- 可视窗口已实际识别手部并绘制 21 点骨架与 6 通道映射。
- macOS `PCAN_USBBUS1 @ 1 Mbps` 已读到 O6 六维状态 `[254,255,254,254,254,254]`。
- 可视真机模式已连接 `mac-pcan-o6`，丢手时统计为 0 条命令，识别到手后进入受限速的实时下发；退出执行安全张开。
- 物品模式已完成双模型摄像头 dry-run，并验证未按 `G` 时保持 `DISARMED`、0 条抓取命令。
- 前景检测测试验证未分类的新物品可被框出；状态机测试验证必须布防、进入区域并连续稳定后才进入 `CLOSING`。
- 本地网页控制台提供实时 MJPEG 画面、250 ms 状态刷新和串行安全动作队列；浏览器不会直接写 CAN。
- 网页双模式共用同一个摄像头线程和一个 O6 控制器；切换模式会安全张开，手势跟随还必须再次明确启用。
- 当前左手地址 `0x28` 已连续三次返回状态 `[254,255,254,254,254,254]`；网页真机启动已验证 `backend=mac-pcan-o6`、`connected=true`、`hand_type=left`。

## 常见问题

`cannot open camera index 0`：在“系统设置 > 隐私与安全性 > 相机”允许 Terminal 或 Codex；关闭占用摄像头的应用。macOS 启动时偶尔返回 1-2 个空帧，程序会自动重试，连续 10 次失败才退出。

`PCAN-Channel handle invalid`：USB-CAN 未连接或未枚举。重新插拔转换器和 O6 电源，再运行 `system_profiler SPUSBDataType`。程序会明确回退 dry-run，不会假装已连真机。

`PCAN adapter opened, but O6 did not return a 6-value state`：转换器在线，但 O6 本体没有响应。检查 O6 电源、CAN-H/CAN-L、终端电阻和左右手 ID。macOS 适配层只有读到六维状态后才会进入真机后端，否则自动回退 dry-run。

`Unsupported platform for CAN interface`：说明绕过了本项目 macOS 适配入口，直接实例化了官方 O6 CAN 类。使用本项目 `app.py --real`。

食指/中指合不拢：先按 `1/2/S` 做视觉标定；再按实际安全范围调整 `channels.*.open/closed`。不要一次把端点改得过激，保留 `max_delta_per_command` 限速。

画面识别但 O6 不动：先确认已切换到 `手势跟随` 并点击 `启用跟随`，再看面板 `backend`。`dry-run` 或 `dry-run-fallback` 不会发送；检查是否误按 `紧急停止`、USB-CAN 是否在线、是否有其他控制进程占用总线。

物品显示 `objects 0`：COCO 模型不认识该类别并不影响通用检测。先清空绿色区、按 `G` 采集背景，再放入物品；它应显示为 `generic-object`。如果物品在按 `G` 之前已经存在，它会成为背景而不会触发。

一直显示 `HAND IN ZONE - BLOCKED`：把放置物品的手完整移出绿色框。这个门禁用于避免夹手，不应通过降低手部检测阈值绕过。

网页显示摄像头不可用：确认 `./run_web.sh` 所在 Terminal/Codex 已获“系统设置 > 隐私与安全性 > 相机”权限，并关闭正在占用 Mac 摄像头的 OpenCV 窗口、FaceTime 或会议软件。一个摄像头通常不能同时被两个本项目进程占用。
