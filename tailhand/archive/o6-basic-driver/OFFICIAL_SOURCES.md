# 官方资料来源

资料快照日期：2026-08-02。

| 内容 | 仓库/页面 | 快照提交 |
|---|---|---|
| Linker Bot 组织仓库列表 | <https://github.com/orgs/linker-bot/repositories> | 动态页面 |
| LinkerHand Python SDK | <https://github.com/linker-bot/linkerhand-python-sdk> | `fbec1057e5320918f634fff103835d9aaa0a2269` |
| Python SDK 中文 README | <https://github.com/linker-bot/linkerhand-python-sdk/blob/main/README_CN.md> | 同上 |
| Python API Reference | <https://github.com/linker-bot/linkerhand-python-sdk/blob/main/doc/API-Reference.md> | 同上 |
| LinkerHand ROS SDK | <https://github.com/linker-bot/linkerhand-ros-sdk> | `2aa379cd11562d953f8b449561107b58c120676e` |
| ROS SDK 中文 README | <https://github.com/linker-bot/linkerhand-ros-sdk/blob/main/README_CN.md> | 同上 |
| MacCAN PCBUSB-Library | <https://github.com/mac-can/PCBUSB-Library> | `9deb4df3ea1053e06a5f1cfb0106897e988d537b` |

官方 SDK 快照仅作为参考；实际 Mac 控制入口为本包的 `driver/run_mac.sh`。官方 LinkerHand O6 Python CAN 类没有 macOS 后端，本包通过 python-can 的 PCAN 接口与 PCBUSB 用户态库实现 Mac 兼容。
