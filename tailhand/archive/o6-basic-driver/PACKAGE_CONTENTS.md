# 压缩包内容与来源

此包把已实测的 LinkerHand O6 左手 Mac 驱动、验证数据和官方参考文档放在一起，便于离线查阅与终端运行。

## 自研驱动

- `driver/o6_driver.py`：基础 CAN 驱动及 CLI。
- `driver/run_mac.sh`：Mac 运行入口。
- `driver/setup_mac.sh`：解压后的环境安装脚本。
- `driver/requirements.txt`：Python 依赖版本。
- `driver/tests/`：不会驱动硬件的模拟 CAN 测试。
- `driver/README.md`：命令与安全说明。
- `driver/VALIDATION_REPORT.md`：真实硬件测试数据。

## 官方 LinkerHand 参考快照

- `official_docs/python-sdk_README_CN.md`
- `official_docs/python-sdk_API-Reference.md`
- `official_docs/ros-sdk_README_CN.md`
- `official_docs/SOURCES.md`：仓库链接、分支与提交版本。

组织仓库入口：<https://github.com/orgs/linker-bot/repositories>

## 第三方 Mac CAN 运行库

`driver/vendor/PCBUSB/` 来自 MacCAN PCBUSB-Library 的 Universal 64-bit 0.13 发行文件。其 EULA 允许随产品再分发完整副本；目录中保留了 LICENSE、COPYRIGHT、README、头文件、示例加载器和原始动态库。

使用该库前请阅读 `driver/vendor/PCBUSB/LICENSE`。该库不提供担保，且上游仅声明支持 PEAK-System PCAN-USB/PCAN-USB FD；本包所用 XCAN-USB 已在当前 Mac 上实测兼容。

来源：<https://github.com/mac-can/PCBUSB-Library>
