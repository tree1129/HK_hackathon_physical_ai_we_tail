# LinkerHand O6 左手：基础 CAN 驱动

这是一套面向 **灵心巧手 O6 左手版** 的小型命令行驱动。参数已固定为：

- 左手 CAN ID：`0x28`
- CAN 速率：`1,000,000 bit/s`
- 6 个控制量依次为：大拇指弯曲、大拇指横摆、食指弯曲、中指弯曲、无名指弯曲、小拇指弯曲
- 每个值范围：`0..255`

运动命令默认只打印 CAN 帧；只有显式加入 `--execute` 才会发送。真正运动前会读取当前位置，运动后必须连续两次到达目标容差范围才返回；若状态异常、温度过高、出现故障码或规定时间内未到位就中止。

## 当前电脑的检测结果

macOS 已识别 USB-CAN：

```text
XCAN-USB
VID:PID = 0c72:000c
bulk endpoints = 0x81, 0x01, 0x82, 0x02
```

官方 LinkerHand Python SDK 的 CAN 后端当前只实现了 Linux `socketcan` 和 Windows `pcan/candle`，在 macOS 会直接报 `Unsupported platform for CAN interface`。本驱动绕开了这个平台判断，并通过 MacCAN `PCBUSB 0.13` 用户态库接入 `python-can`。

本机实测结果：

```text
CAN channel: PCAN_USBBUS1 @ 1 Mbps
O6 firmware: 3.1.1
初始位置: [254, 255, 254, 254, 254, 254]
低速张开后: [250, 250, 250, 250, 250, 250]
温度: [29, 33, 32, 32, 31, 32] °C
故障码: [0, 0, 0, 0, 0, 0]
```

说明 XCAN-USB、MacCAN 和 O6 左手之间的基本收发、状态读取与位置控制均已跑通。

## 安全准备

1. 把机械手可靠固定，运动范围内不要放手指、线缆或硬物。
2. 关闭 ROS 驱动、GUI、动捕手套以及其他可能同时写 CAN 的程序。
3. 第一次只用默认低速 `40`、低扭矩 `80`，先执行张开动作。
4. 随时准备断开机械手电源；软件停止不等于硬件急停。

## Ubuntu 推荐路径

Ubuntu 会把这块 XCAN-USB 映射为 SocketCAN 接口。先确认接口名：

```bash
ip -details link show type can
```

若为 `can0`，手动启用 1 Mbps：

```bash
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can0 up type can bitrate 1000000
ip -details link show can0
```

建立独立环境：

```bash
cd linkerhand_o6_basic_driver
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

先检查，再只读状态：

```bash
python o6_driver.py doctor
python o6_driver.py status
```

预览动作，不发帧：

```bash
python o6_driver.py gesture open
python o6_driver.py gesture fist
python o6_driver.py move 250 250 250 250 250 250
```

第一次实际动作建议只张开：

```bash
python o6_driver.py gesture open --speed 40 40 40 40 40 40 --torque 80 80 80 80 80 80 --execute
```

确认没有卡滞、异响、过热或错误码后，再尝试：

```bash
python o6_driver.py gesture one --execute
python o6_driver.py gesture two --execute
python o6_driver.py gesture fist --execute
```

可用预置动作：`open`、`five`、`fist`、`one`、`two`、`three`、`four`、`ok`、`thumbs_up`。

## 当前 Mac 直接使用

当前工作区已经准备好项目内 PCBUSB 库和 Python 环境。使用包装脚本即可，不需要每次设置动态库路径：

```bash
cd tailhand/archive/o6-basic-driver
./run_mac.sh doctor
./run_mac.sh status
./run_mac.sh gesture open
```

上面的 `gesture open` 只是预览。确认机械手固定牢靠且运动空间清空后，实际执行：

```bash
./run_mac.sh gesture open --execute
./run_mac.sh gesture fist --execute

# 握拳后恢复张开
./run_mac.sh cycle --count 1 --execute

# 连续张合 3 次
./run_mac.sh cycle --count 3 --speed 50 --torque 80 --execute
```

任意六关节位置：

```bash
./run_mac.sh move 250 250 220 250 250 250
./run_mac.sh move 250 250 220 250 250 250 --execute
```

单关节控制会保留其他关节的实时位置：

```bash
./run_mac.sh finger index_pitch 180 --execute
./run_mac.sh finger middle_pitch 100 --speed 40 --torque 80 --execute
```

一次运行全部基础动作，并最终恢复张开：

```bash
./run_mac.sh demo --hold 1.0 --speed 50 --torque 80 --execute
```

四指连续波浪运动（拇指固定、四指带相位差、渐入渐出并最终张开）：

```bash
# 先预览参数和采样姿态
./run_mac.sh wave

# 实际执行已验证的中快速参数
./run_mac.sh wave --duration 5 --frequency 0.8 --amplitude 90 \
  --phase-delay 0.12 --rate 25 --speed 120 --torque 80 --execute
```

建议先保持 `frequency <= 1.0`、`amplitude <= 100`；确认机械手固定可靠且无异常后再逐步调整。

四指达到接近完整握拳行程的波浪参数：

```bash
./run_mac.sh wave --duration 10 --frequency 0.25 --amplitude 250 \
  --phase-delay 0.25 --rate 25 --speed 200 --torque 80 --execute
```

完整行程下不要继续使用 `0.8Hz`：目标变化会超过电机的实际跟随能力，视觉上反而只有小幅动作。

`--speed` 和 `--torque` 可以写一个全局值，也可以写六个独立值：

```bash
./run_mac.sh gesture fist --speed 50 --torque 80 --execute
./run_mac.sh gesture fist \
  --speed 50 50 50 50 50 50 \
  --torque 80 80 80 80 80 80 \
  --execute
```

## 在另一台 macOS 上配置

`python-can` 的 `pcan` 后端在 macOS 需要 MacCAN 的 `PCBUSB` 用户态库。该库有自己的 EULA，而且上游只承诺支持 PEAK-System 的 PCAN-USB/PCAN-USB FD，因此应先在目标电脑上进行只读验证。

请先自行阅读并接受上游许可证，再按上游说明安装 `libPCBUSB.dylib`。本项目不会自动安装或替你接受许可证。安装后：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python o6_driver.py doctor
python o6_driver.py --interface pcan --channel PCAN_USBBUS1 status
```

只有 `status` 能稳定读回 O6 的 6 个位置值及版本信息后，才执行运动：

```bash
python o6_driver.py --interface pcan --channel PCAN_USBBUS1 gesture open --execute
```

如果 PCBUSB 检测不到 XCAN-USB，不要刷写适配器固件；改用 Ubuntu 主机，或把 O6 切换为官方支持的 RS485 模块。

## 与后续 Demo 保持一致

Mac 和 Ubuntu 共用同一个 `o6_driver.py`、动作表、左手 CAN ID 和六关节顺序，只更换 `python-can` 后端：

- Mac：`pcan / PCAN_USBBUS1`
- Ubuntu：`socketcan / can0`

后续 Demo 应从 `O6CanDriver` 调用 `read_status()`、`move_safely()` 和 `GESTURES`，不要在 Demo 中另写一套 CAN 帧。迁移到 ROS 时也保持位置数组顺序不变，只在 ROS `JointState` 与驱动之间增加薄适配层。

## 状态与错误码

`status` 会查询版本、位置、速度、扭矩、温度、故障码和电流。官方定义的故障码：

- `0`：正常
- `1`：电流过载
- `2`：温度过高
- `3`：编码错误
- `4`：过压或欠压

出现非零故障码时，停止运动并断电排查。O6 的官方代码目前没有实现清故障命令。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试使用模拟 CAN 总线，不会控制机械手。
