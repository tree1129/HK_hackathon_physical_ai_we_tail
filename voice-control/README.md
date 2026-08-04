# 机器人动作库语音控制

动态离线口令：识别到右臂动作库中的动作名称后，调用对应动作。动作库变化无需修改语音程序。

查看状态：

```bash
systemctl --user status robot-voice.service
tail -f ~/robot-voice/voice.log
```

停止或启动：

```bash
systemctl --user stop robot-voice.service
systemctl --user start robot-voice.service
```

安全限制：右臂录制或回放时不接受新命令；成功触发后 20 秒内忽略重复识别。

语音按 2 秒窗口连续采集，SenseVoice 模型常驻并只预热一次，通常在说完口令后约 3–5 秒响应。

## 文件

- `asr_daemon.cpp`：常驻 SenseVoice 引擎，通过标准输入接收 WAV 路径。
- `robot_voice_trigger.py`：录音、识别、动作名称匹配和 HTTP 动作调用。
- `robot-voice.service`：systemd 用户服务。

## 依赖与构建

先按照 [SpacemiT Model Zoo ASR](https://github.com/spacemit-com/model-zoo-asr) 准备 SenseVoice 模型并完成 ASR 工程编译。然后在其 `build` 目录链接本程序：

```bash
g++ -std=c++17 -O2 -I../include /path/to/asr_daemon.cpp \
  -o ~/robot-voice/asr_daemon \
  lib/libasr.a -lsndfile -lpthread -lm lib/libsensevoice.a -lfftw3f \
  lib/libzipformer.a /usr/lib/riscv64-linux-gnu/libonnxruntime.so \
  lib/libkaldi-native-fbank-core.a lib/libkissfft-float.a -lcurl
```

将 Python 程序和 service 文件安装到 service 中声明的位置后执行：

```bash
systemctl --user daemon-reload
systemctl --user enable --now robot-voice.service
```

当前硬件路径、HTTP 地址和用户名写在源码/service 顶部，部署到其他板子时需要相应调整。
