# 命令速查

## 网页控制台

```bash
cd apps/o6-camera-teleop
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 只看识别，不控制硬件
./run_web.sh --camera 0 --dry-run

# 当前 Mac 左手真机
./run_web.sh --camera 0 --real
```

网页地址：`http://127.0.0.1:8765`

### 手势跟随

1. 选择 `左手` 或 `右手`，确认后端是真机。
2. 选择 `手势跟随`。
3. 确认画面识别手部与六维预览。
4. 点击 `启用跟随`。
5. 用 `暂停跟随`、`安全张开` 或 `紧急停止`结束动作。

### 物品抓取

1. 选择 `物品抓取`，清空绿色抓取区。
2. 点击 `布防识别`记录背景。
3. 把物品放入掌心与绿色区，并将人的手完全移开。
4. 目标稳定后 O6 限速闭合并保持。
5. 点击 `安全张开`复位。

## OpenCV 本地窗口

```bash
cd apps/o6-camera-teleop
.venv/bin/python app.py --camera 0 --dry-run
.venv/bin/python app.py --camera 0 --real
.venv/bin/python app.py --mode object-grasp --camera 0 --dry-run
```

标定键：`1` 张开、`2` 握拳、`S` 保存、`R` 恢复默认、`O` 安全张开、`E` 急停、`Q` 退出。

## 基础终端驱动

```bash
cd archive/o6-basic-driver
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

./run_mac.sh status
./run_mac.sh gesture open --execute
./run_mac.sh gesture fist --execute
./run_mac.sh gesture one --execute
./run_mac.sh gesture two --execute
./run_mac.sh gesture three --execute
./run_mac.sh cycle --count 3 --speed 50 --torque 80 --execute
./run_mac.sh finger index_pitch 180 --execute
```

四指波浪：

```bash
./run_mac.sh wave --duration 5 --frequency 0.8 --amplitude 90 \
  --phase-delay 0.12 --rate 25 --speed 120 --torque 80 --execute
```

接近完整握拳幅度的慢速波浪：

```bash
./run_mac.sh wave --duration 10 --frequency 0.25 --amplitude 250 \
  --phase-delay 0.25 --rate 25 --speed 200 --torque 80 --execute
```

实际运动前先去掉 `--execute` 预览，并确保机械手固定、运动范围清空、物理断电可立即操作。

