# O6 iPhone 17 Pro LiDAR 自动抓取设计

日期：2026-08-03

状态：已确认，待实施计划

## 1. 目标

在现有 `o6-camera-teleop` 单一运行器中增加 iPhone 17 Pro 腕部 LiDAR 输入，使安装在机械臂腕部、随 O6 一起运动的 iPhone 能够把 RGB、深度和相机数据发送到 Mac。Mac 统一完成物体识别、距离计算、安全状态机、可视化和 O6 六通道指令下发。

系统需要实现以下行为：

- iPhone 与 Mac 位于同一 Wi-Fi。
- iPhone 作为传感器，不直接控制 O6。
- 目标距离虚拟接触面不超过 `5 cm` 时，O6 保持安全张开。
- 目标稳定越过 `0 cm` 虚拟接触面时，O6 执行抓握。
- 网页同时显示 RGB、深度、目标、采样区域、距离、状态机和 O6 指令。
- 手势跟随和自动抓取仍是单一运行器内的两个互斥模式。
- 默认使用 dry-run，完成深度验证和标定后才允许真机测试。

## 2. 非目标

本阶段不包含：

- 机械臂的空间运动、轨迹规划或避障；机械臂或操作者负责让腕部/O6 靠近物体。
- ROS、MoveIt、URDF、强化学习或复杂重定向优化器。
- 使用单目图像估算真实厘米距离。
- 自动选择抓取类型、六自由度抓取位姿或复杂物体姿态估计。
- 无人值守自动布防、自动解除急停或自动松手。
- 将实时 RGB 或深度数据上传到云端或默认写入磁盘。

## 3. 现有系统约束

现有 Mac 应用位于 `apps/o6-camera-teleop/`，包含：

- Flask 网页控制台，默认监听 `127.0.0.1:8765`。
- `WebConsoleRuntime` 单一视觉与控制运行器。
- MediaPipe 手势跟随。
- EfficientDet Lite 物体检测和现有目标稳定状态机。
- `O6Controller`、EMA、死区、最大变化量和发送频率限制。
- 手势跟随/自动抓取互斥模式、左右手切换、张开、布防、解除布防和软件急停。

新增功能必须复用这些边界，不创建第二个可以同时控制 O6 的进程。

## 4. 总体架构

```text
iPhone 17 Pro
  SwiftUI + ARKit
  RGB + smoothedSceneDepth + confidence + intrinsics + pose
            |
            | local Wi-Fi, WebSocket, target 15 FPS
            v
Mac DepthReceiver (port 8766)
  pairing, validation, decoding, freshness checks
            |
            v
Object detector + DepthGeometry
  target ROI, robust depth, signed contact-plane distance
            |
            v
Existing grasp state machine + safety gates
            |
            v
Existing CommandFilter + O6Controller
            |
            v
LinkerHand O6
```

网页控制台继续只监听 `127.0.0.1:8765`。只有传感器接收端口 `8766` 对局域网开放。iPhone 不能调用网页动作接口，也不能直接向 O6 发送姿态。

## 5. iPhone 采集端

新增目录：

```text
apps/o6-depth-streamer-ios/
```

iOS 应用使用 SwiftUI、ARKit 和系统网络 API，不引入第三方运行时依赖。

### 5.1 ARKit 会话

- 使用后置相机和 `ARWorldTrackingConfiguration`。
- 启用 `sceneDepth`，优先读取 `smoothedSceneDepth`。
- 若设备不支持场景深度，界面显示明确错误且不建立有效数据流。
- RGB 发送分辨率目标为 `640x480`，JPEG 质量以网络稳定为优先。
- 深度使用 ARKit 原始深度分辨率，转换成毫米单位的 little-endian `uint16`；`0` 表示无效深度。
- 发送深度置信度图；Mac 仅使用达到配置阈值的像素。
- RGB 与深度在 iPhone 端统一到同一显示方向，并发送从图像坐标到深度坐标所需的变换信息。
- 采集可以高于 15 FPS，但网络发送限频为 15 FPS；拥塞时丢弃旧帧，不排队积压。

### 5.2 连接界面

iPhone 应用显示：

- ARKit/LiDAR 可用状态。
- 自动发现到的 Mac 接收端。
- 手动输入 Mac IP 的回退入口。
- 临时配对码输入。
- 连接状态、发送 FPS、最近延迟和有效深度比例。
- RGB 预览和中心深度读数，用于安装时快速检查。

Mac 使用 Bonjour 发布 `_o6depth._tcp` 服务。Bonjour 发现失败时，用户可以输入 Mac IP 和端口 `8766`。

## 6. 局域网协议

### 6.1 会话

- 传输使用 WebSocket。
- Mac 每次启动生成新的临时配对码。
- iPhone 首先发送 JSON `hello`，包含协议版本、配对码、设备型号和深度能力。
- Mac 校验成功后只接受一个活动 iPhone 会话；新会话不能静默替换当前会话。
- 配对失败、协议版本不兼容或已有活动设备时返回明确错误并关闭连接。
- 自动抓取仍需用户在本地网页手动布防；配对成功本身不能产生动作。

### 6.2 帧格式

每个数据帧使用一个二进制 WebSocket 消息：

```text
4 bytes big-endian JSON header length
UTF-8 JSON header
JPEG RGB bytes
little-endian uint16 depth bytes
uint8 confidence bytes
```

JSON 头至少包含：

- `protocol_version`
- `sequence`
- `timestamp_ns`
- RGB 宽高和字节长度
- 深度宽高和字节长度
- 置信度字节长度
- 图像方向
- 相机内参 `fx/fy/cx/cy`
- RGB/深度坐标变换
- ARKit 相机位姿
- 深度单位，固定为毫米

Mac 接收端执行以下限制：

- 最大消息尺寸默认 `1.5 MiB`。
- 最大接受频率默认 `20 FPS`。
- 序号必须递增，时间戳不得倒退。
- 超过 `500 ms` 的帧视为过期。
- 所有长度、维度和缓冲区大小必须相互一致。
- 解析失败只记录有界错误信息，不进入视觉或控制流程。

### 6.3 安全边界

首版面向可信本地 Wi-Fi，不把临时配对码视为互联网级身份认证。配对码用于防止局域网中的误连接，并且只允许上传传感器帧。真实动作仍受本地网页手动布防、目标稳定、人手阻挡、限速和急停共同约束。接收端不得暴露 O6 动作方法，也不得把来自 iPhone 的任何字段解释为手部姿态命令。

## 7. Mac 组件

在现有应用中增加以下独立模块：

```text
vision/depth_protocol.py    # 帧编码约束和严格解析
vision/depth_receiver.py    # WebSocket、Bonjour、配对和最新帧缓存
vision/depth_geometry.py    # ROI 深度、坐标映射和有符号距离
```

`WebConsoleRuntime` 仍然是唯一控制所有权持有者。`DepthReceiver` 只提供不可变的最新传感器帧，不持有 `O6Controller`。

Mac 端新增 `websockets` 和 `zeroconf` 依赖，分别负责传感器 WebSocket 和 Bonjour 发布。接收服务在独立后台线程中运行，通过容量为 1 的最新帧缓存与运行器通信；消费者来不及时覆盖旧帧。

自动抓取模式增加输入源：

- `mac-camera`：保留现有普通摄像头演示，但不输出厘米距离。
- `iphone-lidar`：启用本设计的深度抓取逻辑。

切换输入源时必须解除布防并清空目标稳定计数。

当输入源为 `iphone-lidar` 时，不要求 Mac 摄像头可用；目标检测和人手阻挡检测均使用 iPhone RGB。切换回手势跟随或 `mac-camera` 后再使用 Mac 摄像头。输入源生命周期由同一个运行器负责，不能并行启动第二个 O6 控制进程。

## 8. 目标深度与有符号距离

### 8.1 目标选择

- 继续使用现有 EfficientDet Lite 在 RGB 图像上产生候选框。
- 继续使用现有抓取区域、类别过滤、中心稳定度和面积限制。
- 检测到人手进入抓取区域时，现有 `hand_blocked` 安全门继续生效。
- 多个候选目标存在时，只追踪当前稳定目标；目标身份或中心突变会重置稳定计数。

### 8.2 深度采样

- 将 RGB 目标框映射到深度坐标。
- 使用目标框中心区域，避免边缘混入背景。
- 丢弃零深度、低置信度、非有限值和配置范围外的像素。
- 使用中位数和中位绝对偏差过滤飞点。
- 有效像素比例不足时，该帧距离无效。
- 距离滤波只作用于有效且属于同一稳定目标的样本。

### 8.3 接触面标定

iPhone 固定到腕部后，用户把实体平面放在期望触发抓握的位置，并在网页点击“记录 0 cm 接触面”。系统在目标区域采集多帧稳健中位数作为 `contact_depth_mm`。

有符号距离定义为：

```text
signed_distance_mm = target_depth_mm - contact_depth_mm
```

- 正值：目标仍在虚拟接触面外侧。
- `0`：目标到达已标定触发面。
- 负值：目标比标定面更靠近相机。

LiDAR 本身不会输出负深度；负值只表示相对于已标定虚拟接触面的方向。重新安装或移动 iPhone 后必须重新标定。

## 9. 抓握行为

新增深度阶段但不复制 O6 主状态机：

- `DEPTH_UNAVAILABLE`
- `OUTSIDE_OPEN_ZONE`
- `PREGRASP_OPEN`
- `CONTACT_CONFIRMED`

默认阈值：

- `open_threshold_mm: 50`
- `contact_threshold_mm: 0`
- `contact_stable_frames: 8`
- `stream_timeout_ms: 500`

行为如下：

1. 未连接、未标定、未布防或深度无效时禁止闭合。
2. 距离大于 `5 cm` 时只监测目标，不产生自动抓握命令。
3. 距离不超过 `5 cm` 且大于 `0 cm` 时，发送或维持配置中的安全张开姿态。
4. 距离不超过 `0 cm` 且连续稳定 8 帧时，将现有抓取状态机推进到 `CLOSING`。
5. 抓握姿态仍经过现有命令频率、EMA、死区和最大变化量限制。
6. 到达 `HOLDING` 后保持最后抓握姿态；目标丢失或距离回升不能自动松手。
7. 网页“张开”、正常退出流程或用户明确的释放操作可以松手，并解除布防。
8. 软件急停锁定后停止新指令；模式切换、重连或重新布防不能自动解除急停。

“5 cm 张开”是接近阶段的预抓取行为，不代表系统控制机械臂前进。

## 10. 断流与异常

- 布防但尚未抓握时断流：解除布防、清空稳定计数、停止下发。
- 正在闭合时断流：停止产生新命令，保持已经发送的最后姿态。
- 已处于 `HOLDING` 时断流：保持抓握，不自动张开。
- RGB 可用但深度不可用：只显示画面，不允许基于面积或单目结果伪造厘米距离。
- 接收线程异常：隔离到传感器层，运行器显示错误并关闭自动抓握入口。
- O6 SDK 初始化失败：继续沿用现有明确报错和 dry-run 回退。
- 正常关闭真机运行器：继续执行现有安全张开和设备释放流程。

软件急停不是经过安全认证的硬件急停。真机试验仍需要物理断电手段和无夹伤风险的测试区域。

## 11. 网页控制台

在现有页面中增加：

- 自动抓取输入源选择：`Mac 摄像头 / iPhone LiDAR`。
- iPhone 连接状态、设备名、发送 FPS、延迟、有效深度比例和配对码。
- RGB 与深度伪彩视图；窄屏时上下排列。
- RGB 目标框、深度采样区和实时有符号距离。
- `5 cm` 预抓取状态和 `0 cm` 接触状态。
- “记录 0 cm 接触面”和“清除深度标定”按钮。
- 未连接、未标定、未布防、预抓取、稳定确认、闭合、保持、断流保持和急停状态。

保留并复用：

- 手势跟随/自动抓取互斥模式。
- 左手/右手切换。
- 布防、解除布防、张开和急停。
- 六通道姿态显示、后端状态和错误诊断。

所有改变控制状态的动作继续通过现有动作队列串行处理。

新增本地动作名称：

- `source-mac-camera`
- `source-iphone-lidar`
- `depth-calibrate-contact`
- `depth-clear-calibration`

新增状态字段至少包括 `vision_source`、`iphone_connected`、`iphone_device`、`depth_fps`、`depth_latency_ms`、`depth_valid_ratio`、`depth_calibrated`、`contact_depth_mm`、`signed_distance_mm`、`depth_phase` 和 `pairing_code`。深度伪彩通过独立的本地 MJPEG 路由提供，不能由 iPhone 直接访问网页。

## 12. 配置

`config.yaml` 新增 `iphone_lidar` 段，默认值如下：

```yaml
iphone_lidar:
  enabled: true
  bind_host: 0.0.0.0
  port: 8766
  service_name: _o6depth._tcp
  target_fps: 15
  max_fps: 20
  max_message_bytes: 1572864
  stream_timeout_ms: 500
  min_confidence: medium
  min_valid_depth_ratio: 0.20
  roi_inner_ratio: 0.50
  open_threshold_mm: 50
  contact_threshold_mm: 0
  contact_stable_frames: 8
  contact_depth_mm: null
```

标定值可以通过网页保存到配置。写入必须保留其他配置项和用户现有标定。

配置保存使用临时文件加原子替换，避免进程中断留下半写文件。运行器持有配置写入锁，网页请求只把标定动作放入现有动作队列。

## 13. 测试

### 13.1 自动测试

- 协议正常帧、截断帧、长度不一致、超大帧和版本不兼容。
- 序号、时间戳、频率限制和 `500 ms` 过期判断。
- 深度 ROI 映射、无效值过滤、中位数和飞点过滤。
- `contact_depth_mm` 和有符号距离方向。
- `5 cm` 张开、`0 cm` 稳定 8 帧闭合以及计数重置。
- 未标定、未布防、低有效深度、人手阻挡和断流禁止闭合。
- `HOLDING` 断流保持、手动张开解除布防和急停锁定。
- 所有 O6 指令长度为 6，且每个值位于 `0–255`。
- 模式或输入源切换时只有一个 O6 控制所有者。

### 13.2 集成与硬件验收

按以下顺序执行：

1. 使用合成 RGB/深度帧运行 Mac 单元和集成测试。
2. iPhone 17 Pro 连接 Mac，在 dry-run 下显示实时 RGB、深度、FPS 和延迟。
3. 使用标尺和平面验证 `10 cm`、`5 cm`、`0 cm` 附近的距离方向和稳定性。
4. 验证遮挡、低纹理、反光、目标离开和 Wi-Fi 断开不会触发闭合。
5. 在 dry-run 下验证完整布防、预抓取、接触确认、闭合和保持流程。
6. O6 空载、低速、无遮挡环境下进行真机张开和抓握。
7. 最后在软质、无危险物体上验证腕部接近触发；测试者保持可立即断电。

## 14. 完成标准

- iPhone 17 Pro 能通过同一 Wi-Fi 稳定发送 RGB 和 LiDAR 深度到 Mac。
- 网页可视化从目标识别到 O6 六通道输出的完整链路。
- 接触面标定后，距离符号与实际接近方向一致。
- `5 cm` 进入预抓取张开，稳定越过 `0 cm` 后抓握。
- 深度无效、断流、未布防、人手阻挡和急停状态下不会异常闭合。
- 手势跟随与自动抓取保持互斥，且只有一个 O6 运行器。
- dry-run 无 O6 时可完成全部视觉、网络、标定和状态机验证。
- README 包含 Xcode/iPhone 部署、局域网连接、标定、dry-run、真机和排错说明。
