# B 电脑部署指南

> 这份文档是给 B 电脑的运维人员看的，照着做就能加入 A2A Mesh 协作网络。
> 
> **预计时间：15-20 分钟**

---

## 一、项目简介

**A2A Mesh** 是一个让多台电脑上的 AI Agent 互相通信的框架。

- 阿里云 ECS 跑中央 Hub Server（已经部署好了）
- 每台电脑跑一个 Agent Daemon 保持长连接
- 通过 Hub 路由消息，跨网络、跨地域都能通信

**典型用途**：A 电脑的 Claude 写代码 → 自动发给 B 电脑的 Claude 测试 → 测试报告回给 A → A 修改 → 循环。

---

## 二、你需要准备的信息

跟 A 电脑的运维拿这些信息：

| 信息 | 示例 | 说明 |
|------|------|------|
| **Hub 地址** | `ws://8.156.83.217:8086` 或 `wss://hub.xingye.xin` | ECS 公网地址 |
| **你的 computer ID** | `computer-B` | 唯一标识，不要跟别人重复 |
| **你的 Token** | `tok-B-xxxxxxxx` | Bearer Token，A 那边会生成给你 |

---

## 三、环境要求

### macOS（推荐）

```bash
# 检查 Python（要 3.8+）
python3 --version

# 如果 < 3.8，装一个新版
brew install python@3.11
which python3.11  # 记下路径
```

### Linux

```bash
python3 --version
# 大部分 Linux 自带 3.8+
```

### Windows

```powershell
python --version
# 如果 < 3.8，去 https://www.python.org/downloads/ 装一个
```

---

## 四、部署步骤

### Step 1：克隆代码

```bash
cd ~/Documents
git clone git@github.com:136500201/AI-Agent-Comm.git a2a-mesh
cd a2a-mesh
```

**如果 SSH 拉取失败**（GitHub 没加你的公钥）：
- 跟 A 电脑运维要 GitHub 用户名
- 或者用 HTTPS：`git clone https://github.com/136500201/AI-Agent-Comm.git a2a-mesh`

### Step 2：安装依赖

```bash
pip3 install -r agent/requirements.txt
```

> macOS 用户如果遇到权限错误，加 `--user`：
> ```bash
> pip3 install --user -r agent/requirements.txt
> ```

### Step 3：配置环境变量

把下面内容存到 `~/.a2a-mesh.env`（**权限必须是 600**）：

```bash
cat > ~/.a2a-mesh.env <<EOF
export HUB_URL=ws://8.156.83.217:8086
export COMPUTER_ID=computer-B
export TOKEN=tok-B-xxxxxxxx
EOF

chmod 600 ~/.a2a-mesh.env
```

⚠️ **把 `ws://8.156.83.217:8086` 换成实际的 Hub 地址，`tok-B-xxxxxxxx` 换成实际给你的 Token。**

### Step 4：启动 Agent

**前台跑（看日志用）**：

```bash
source ~/.a2a-mesh.env
cd ~/Documents/a2a-mesh
python3 agent/daemon.py --id "$COMPUTER_ID" --token "$TOKEN" --hub "$HUB_URL"
```

应该看到：

```
[2026-xx-xx] 连接 Hub: ws://8.156.83.217:8086/ws/computer-B?token=xxx
============================================================
A2A Mesh Agent - computer-B
============================================================
✅ computer-B 已上线
[computer-B]>
```

看到 `✅ 已上线` 就成功了！Agent 会一直跑着接收消息。

**后台跑（生产用）**：

macOS / Linux：

```bash
# 启动
nohup python3 agent/daemon.py --id "$COMPUTER_ID" --token "$TOKEN" --hub "$HUB_URL" \
  < /dev/null > ~/a2a-agent-B.log 2>&1 &
echo $! > ~/a2a-agent-B.pid
echo "PID: $(cat ~/a2a-agent-B.pid)"

# 停止
kill $(cat ~/a2a-agent-B.pid)

# 看日志
tail -f ~/a2a-agent-B.log
```

macOS 推荐做成 LaunchAgent（开机自启）：

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.a2amesh.agent.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.a2amesh.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/YOUR_USERNAME/Documents/a2a-mesh/agent/daemon.py</string>
        <string>--id</string><string>computer-B</string>
        <string>--token</string><string>tok-B-xxxxxxxx</string>
        <string>--hub</string><string>ws://8.156.83.217:8086</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/tmp/a2a-agent-B.log</string>
    <key>StandardErrorPath</key><string>/tmp/a2a-agent-B.err</string>
</dict>
</plist>
EOF

# ⚠️ 改 YOUR_USERNAME 为你的 macOS 用户名（echo $USER）
# ⚠️ 改 python3 路径为 which python3 的输出
# ⚠️ 改 token 和 hub 为实际值

launchctl load ~/Library/LaunchAgents/com.a2amesh.agent.plist
```

---

## 五、验证连接

启动后让 A 电脑发一条测试消息给你。预期效果：

**B 电脑 Agent 日志**：
```
🔍 RAW 收到: {"jsonrpc":"2.0","id":"test-xxx",...}
📨 收到任务 (id=test-xxx)
⚙️  处理任务: requirement_clarification from computer-A
📝 已回包: id=test-xxx
📤 已发送: id=test-xxx
```

或者手动测一下（用 CLI）：

```bash
cd ~/Documents/a2a-mesh
HUB_HTTP=http://8.156.83.217:8086 TOKEN=tok-B-xxxxxxxx python3 cli/ai_send.py send \
  --from computer-B --to computer-A --type echo --text "B 电脑已上线 ✅"
```

---

## 六、常见问题

### Q1: 连接超时

```bash
# 先测端口
nc -zv 8.156.83.217 8086
```

- 不通 → A 那边 ECS 安全组没放行你的公网 IP，让 A 加白名单
- 通但 daemon 报错 → 看 Token 对不对

### Q2: Permission denied (publickey) / Token 错

检查三件事：

```bash
# 1. Hub 地址对吗
echo $HUB_URL

# 2. Token 对吗（看末尾）
echo $TOKEN

# 3. Computer ID 是不是唯一的
echo $COMPUTER_ID
```

### Q3: Python 版本太低

macOS 自带 Python 2.7/3.x 都有可能。推荐装 pyenv 或 conda：

```bash
brew install pyenv
pyenv install 3.11
pyenv global 3.11
```

### Q4: 中文乱码

macOS 终端默认 UTF-8 一般没事。如果乱码：

```bash
export LANG=zh_CN.UTF-8
export LC_ALL=zh_CN.UTF-8
```

### Q5: 想看历史消息

```bash
HUB_HTTP=http://8.156.83.217:8086 TOKEN=tok-B-xxxxxxxx \
  python3 cli/ai_send.py history computer-B --limit 20
```

---

## 七、下一步

1. ✅ 启动 Agent 后告诉 A："我上线了"
2. A 会发个测试任务给你
3. 测试通过后，A 会发起真实协作任务（需求澄清、代码评审、Bug 复现等）

---

## 八、联系

遇到问题找 A 电脑的运维，提供：
1. Agent 日志（`~/a2a-agent-B.log` 或 `tail /tmp/a2a-agent-B.log`）
2. `python3 --version` 输出
3. `nc -zv 8.156.83.217 8086` 输出

---

**最后更新**：2026-09-08  
**项目地址**：https://github.com/136500201/AI-Agent-Comm
