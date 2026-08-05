# 疯狂原始人 · Physical AI 机器人平台

香港 Physical AI Hackathon 项目：基于 Onero A1 机械臂、K3 RISC-V 边缘计算板、
reCamera 与 LinkerHand 的视觉感知、动作示教、语音控制和物品靠近系统。

## 功能

- 零力示教、动作录制、分类动作库与轨迹回放
- Web 三维末端/关节控制界面
- reCamera 实时画面和地面物品检测
- 视觉闭环平滑靠近（默认关闭，不控制夹爪）
- 浏览器语音识别与动作触发
- USB-CAN 稳定硬件 ID、断线检测和自动恢复
- systemd 开机看门狗与一键启动脚本

## 目录

- `dashboard/`：机械臂控制服务、可视化界面、视觉服务和运维脚本
- `voice-control/`：离线语音识别与动作触发服务
- `board-tools/`：从 K3 板实际导出的机械臂状态与动作调试源码

详细部署方式见 [`dashboard/README.md`](dashboard/README.md)。

## 安全

机械臂运动前应确认设备固定、工作空间无人无障碍并准备急停。视觉靠近服务重启后
保持关闭，必须由操作者从界面明确启动。
