# O6 Depth Streamer for iPhone 17 Pro

这个 iOS 应用使用 iPhone 17 Pro 的后置相机、ARKit `sceneDepth` 和 LiDAR，将 RGB、毫米深度与置信度通过同一 Wi-Fi 发送给 Mac。Mac 才负责目标识别、距离门禁和 LinkerHand O6 控制；iPhone 不直接控制机械手。

本项目只驱动 O6 手指，不控制机械臂或手腕。相机看到目标不会让机械臂自动靠近，接近动作必须由人或独立的机械臂控制器完成。

## 环境

- macOS 上安装 Xcode 与 Homebrew。
- iPhone 17 Pro，iOS 17 或更高，已开启开发者模式。
- iPhone 与运行控制台的 Mac 在同一 Wi-Fi，网络不能启用会隔离客户端的访客模式。
- Mac 端项目依赖已安装，并能运行 `apps/o6-camera-teleop/run_web.sh`。

## 生成并打开工程

工程由 `project.yml` 生成。每次修改该文件后重新执行 `xcodegen generate`，不要手工依赖生成文件中的临时设置。

```bash
brew install xcodegen
cd tailhand/apps/o6-depth-streamer-ios
xcodegen generate
open O6DepthStreamer.xcodeproj
```

在 Xcode 中完成以下设置：

1. 选择左侧项目，再选 `O6DepthStreamer` target。
2. 打开 `Signing & Capabilities`，保持 `Automatically manage signing`，在 `Team` 选择自己的 Personal Team 或开发团队。
3. 用数据线连接名为 `Duami` 的 iPhone 17 Pro，在手机上选择“信任这台电脑”。
4. 在 Xcode 顶部目标列表选择 `Duami`，不要选模拟器。LiDAR `sceneDepth` 不能用模拟器完成硬件验收。
5. 若 Xcode 提示不可运行，在 iPhone 的“设置 > 隐私与安全性 > 开发者模式”开启开发者模式并按系统要求重启。
6. 点击 Run 安装。若免费 Personal Team 的 bundle ID 冲突，可在 Xcode 中把 `com.duamixu.tailhand.O6DepthStreamer` 改成自己的唯一标识；不要修改 Mac 端协议。

首次打开应用时允许：

- `相机`：采集 RGB 与 ARKit 深度。
- `本地网络`：发现并连接 Mac 的 `_o6depth._tcp` 服务。

误点拒绝后，到 iPhone“设置 > 隐私与安全性 > 相机”和“设置 > 隐私与安全性 > 本地网络”重新开启 O6 Depth Streamer 权限。

## Mac 端先启动

先用 dry-run，避免配置或距离方向错误时驱动真机：

```bash
cd tailhand/apps/o6-camera-teleop
./run_web.sh --dry-run
```

Safari 或 Chrome 只在 Mac 上打开：

```text
http://127.0.0.1:8765
```

网页控制台绑定 `127.0.0.1:8765`，不向局域网开放。iPhone 连接的是 Mac `0.0.0.0:8766` 的 RGB-D WebSocket。macOS 第一次弹出防火墙提示时，允许 Python 或 Terminal 接收入站连接；若曾拒绝，在“系统设置 > 网络 > 防火墙 > 选项”允许对应程序。不要把 `8765` 填到 iPhone。

## 配对与传输

1. Mac 网页选择 `物品抓取` 和 `iPhone LiDAR`，记下六位配对码。
2. 在 iPhone 打开应用。保持横屏右向，并确认预览有画面、中心距离不是 `—`。
3. 在“Mac 接收端”选择自动发现的 `O6 Depth Receiver`，输入六位码，点击 `连接`。
4. iPhone 显示“正在传输”后，Mac 网页应显示设备名、RGB、深度伪彩、发送 FPS、延迟和有效深度比例。

每次 Mac 运行器启动都会生成新配对码；只允许一个 iPhone 或合成发送器连接。配对成功不等于布防，也不会自行闭合 O6。

Bonjour 没有发现 Mac 时，在 iPhone 开启“手动输入 Mac 地址”，填写 Mac 的 Wi-Fi IP 和端口 `8766`。Mac 地址可在“系统设置 > Wi-Fi > 详情 > TCP/IP”查看，也可在 Terminal 尝试：

```bash
ipconfig getifaddr en0
```

若命令无输出，以系统设置显示的当前 Wi-Fi 地址为准。VPN、访客 Wi-Fi、企业 AP 客户端隔离和防火墙都可能阻止 `8766`。

## 安装姿态与 0 cm 标定

把 iPhone 牢固安装在机械腕部，让后置相机随 O6 一起运动。画面应覆盖手背、指尖接触区域和目标；不要让支架遮挡 LiDAR。标定后只要相机与 O6 的相对位置发生变化，就必须重新标定。

严格按顺序操作：

1. 保持 O6 安全张开且未布防。
2. 把平面目标放在希望定义为指尖接触的平面。
3. 确认 Mac 的目标采样框落在平面上，深度有效比例稳定。
4. 点击 Mac 网页 `记录 0 cm`，保持目标不动，等待 15 个样本完成。
5. 移开平面，确认目标位于接触面之外时显示正距离；越过接触面时显示负距离。
6. 点击 `布防识别` 后再开始缓慢接近测试。

默认阈值的含义：

| 有符号距离 | 网页深度阶段 | O6 行为 |
| --- | --- | --- |
| `> +50 mm` | 范围外 | 监测，不产生自动抓握 |
| `0 < 距离 <= +50 mm` | 预抓取张开 | 维持安全张开 |
| `<= 0 mm`，不足 8 帧 | 接触确认中 | 累计稳定帧，不闭合 |
| `<= 0 mm`，连续 8 帧 | 接触确认 | 允许状态机进入 `CLOSING` |

到达 `HOLDING` 后，即使深度断流也保持已发送姿态，不会自动松手。尚未闭合时断流超过 `500 ms` 会解除布防并禁止闭合；闭合过程中断流则停止生成新命令并保持最后姿态。

## 释放、急停与真机

点击 Mac 网页 `安全张开` 会明确释放并解除布防。`紧急停止` 会锁存软件停止，之后模式切换、重新配对或布防都不会解除；必须重启 Mac 运行器。软件急停不是安全认证设备，也不保证在通信故障时主动张开，真机测试必须在无夹伤风险区域并保留物理断电手段。

dry-run 完整验证后，回到 Mac Terminal 按 `Ctrl-C` 停止，再连接正确左右手的 O6 并运行：

```bash
./run_web.sh --real
```

确认网页后端显示真实硬件且 `connected=true`，再重新配对、标定和布防。正常结束仍使用 `Ctrl-C`；真机在线且未急停时，Mac 会先安全张开再释放连接。

## 构建检查

模拟器可验证编译和编码器单元测试，但不能验证 LiDAR：

```bash
xcodebuild \
  -project O6DepthStreamer.xcodeproj \
  -scheme O6DepthStreamer \
  -sdk iphonesimulator \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro,OS=latest' \
  test CODE_SIGNING_ALLOWED=NO
```

## 常见问题

`此设备没有 sceneDepth`：必须在支持 LiDAR 的 iPhone 17 Pro 真机运行；模拟器和非 Pro 设备不能提供本链路要求的真实厘米深度。

`正在搜索` 一直不结束：确认两台设备同一 Wi-Fi、本地网络权限已开、防火墙允许 `8766`，再使用手动 Mac IP。

`连接失败` 或配对被拒绝：确认使用网页本次启动显示的新六位码，并断开其他 iPhone 或合成发送器。

有 RGB 但没有有效深度：移除 LiDAR 前的遮挡，避免过近、反光、透明或低纹理目标；系统不会用单目面积伪造厘米距离。

距离方向相反或接触点漂移：停止布防，点击 `清除深度标定`，检查相机支架，再从固定的接触平面重新记录 `0 cm`。
