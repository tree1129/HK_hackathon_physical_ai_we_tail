# O6 硬件、SDK 与协议笔记

## 六维顺序

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

## 当前左手实测

```text
设备：LinkerHand O6 左手
CAN channel：PCAN_USBBUS1
bitrate：1,000,000 bit/s
CAN ID：0x28
状态帧：01 fe ff fe fe fe fe
解码位置：[254, 255, 254, 254, 254, 254]
安全张开：[250, 250, 250, 250, 250, 250]
真机网页后端：mac-pcan-o6
```

早期基础驱动还记录到：

```text
O6 firmware：3.1.1
温度：[29, 33, 32, 32, 31, 32] C
故障码：[0, 0, 0, 0, 0, 0]
USB-CAN：XCAN-USB，VID:PID 0c72:000c
```

## CAN 帧

- 左手 ID：`0x28`
- 右手 ID：`0x27`
- 位置查询：向手 ID 发送数据 `[0x01]`
- 位置下发：`[0x01, ch0, ch1, ch2, ch3, ch4, ch5]`
- 速度下发：`[0x05, s0, s1, s2, s3, s4, s5]`

macOS 适配层只有在查询得到 6 个位置值后才进入真实后端。适配器能打开但没有状态响应时，程序回退 `dry-run-fallback`。

## 官方 Python SDK 核对

固定提交：`fbec1057e5320918f634fff103835d9aaa0a2269`

```python
from LinkerHand.linker_hand_api import LinkerHandApi

hand = LinkerHandApi(
    hand_type="left",
    hand_joint="O6",
    modbus="None",
    can="can0",
)
hand.set_speed(speed=[50] * 6)
hand.finger_move(pose=[250] * 6)
state = hand.get_state()
```

源码与文档差异：

- 实际设置文件位于 `LinkerHand/config/setting.yaml`。
- 官方 O6 CAN 后端只覆盖 Linux SocketCAN 和 Windows PCAN/Candle，没有 Darwin 分支。
- `LinkerHandApi.close_can()` 在该提交中引用未绑定的 `modbus` 变量；本项目在适配层关闭底层设备。
- SDK 完整 requirements 包含 O6 运行不需要的 MuJoCo、PyQt 等依赖；主项目 requirements 只安装视觉、网页、CAN 和串口运行依赖。

## 平台路径

### macOS

- 摄像头：OpenCV 索引 `0`。
- CAN：`python-can` 的 `pcan` 接口、`PCAN_USBBUS1`、随项目保留的 MacCAN PCBUSB 动态库。
- 运行：`./run_web.sh --camera 0 --real`。

### Ubuntu

- CAN：官方 SDK + `socketcan/can0`。
- 配置：`sudo ip link set can0 up type can bitrate 1000000`。
- 不要同时运行 ROS SDK、网页控制台和其他写 CAN 的程序。

### RS485

- 官方 O6 RS485 默认 115200 baud。
- Linux 示例 `/dev/ttyUSB0`，macOS 示例 `/dev/cu.usbserial-XXXX`。
- 把 `config.yaml > o6 > modbus` 改成实际端口后走官方 SDK。

