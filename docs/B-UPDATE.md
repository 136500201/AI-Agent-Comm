# B 端代码更新指南

> **场景**：Hub/A 端修复了关键 bug，B 端 daemon 是旧代码，需要同步更新才能让 A↔B 通信正常。
>
> **预计时间：2 分钟**

---

## 一、为什么需要更新

A 电脑 ↔ Hub 端修了一堆 bug（回包路由、持久化、pending 补推等）。但 Hub 修复后，B 端 daemon 还在跑旧代码：

| 文件 | 状态 | 影响 |
|------|------|------|
| `hub/server.py` | A 电脑已推送并重启 | ✅ 已经在 ECS 上更新 |
| `agent/daemon.py` | **B 端是旧版本** | ❌ 还在循环处理 result，B 端表现异常 |
| `cli/ai_send.py` | 没变 | ✅ 不需要更新 |

如果 B 不重启 daemon，A 发的任务可能被 B 接收但不会正确回包（旧的 daemon 把 result 当成任务处理，产生空 result 循环）。

---

## 二、更新步骤

### Step 1：拉最新代码

SSH 到 B 电脑（你的 B 电脑应该已经配好 SSH 了），然后：

```bash
cd ~/Documents/a2a-mesh   # 或你之前 clone 的路径
git pull origin main
```

应该看到：

```
remote: Counting objects: ...
Updating 67b807f..8f72d72
Fast-forward
 agent/daemon.py | 7 +++++--
 hub/server.py   | 54 ++++++++++++++++++++++++++++++++----
 README.md       | 25 +++++++++++++++++++++----
 docs/B-DEPLOY.md | 275 +++++++++++++++++++++++++++++++
```

### Step 2：停掉旧 daemon

```bash
# 如果你是 nohup 启动的
kill $(cat ~/a2a-agent-B.pid)

# 如果你是 LaunchAgent 启动的（macOS）
launchctl unload ~/Library/LaunchAgents/com.a2amesh.agent.plist

# 确认 daemon 已停
ps aux | grep daemon.py | grep -v grep
# 应该没输出
```

### Step 3：重启 daemon

**前台测试**（先确认能跑）：

```bash
cd ~/Documents/a2a-mesh
source ~/.a2a-mesh.env
python3 agent/daemon.py --id "$COMPUTER_ID" --token "$TOKEN" --hub "$HUB_URL"
```

看到：

```
[2026-xx-xx xx:xx:xx] 连接 Hub: ws://8.156.83.217:8086/ws/computer-B?token=xxx
✅ computer-B 已上线
[computer-B]> 
```

按 `Ctrl+C` 退出前台测试。

**后台启动**：

```bash
# macOS LaunchAgent 方式
launchctl load ~/Library/LaunchAgents/com.a2amesh.agent.plist

# 或 nohup 方式
nohup python3 agent/daemon.py --id "$COMPUTER_ID" --token "$TOKEN" --hub "$HUB_URL" \
  < /dev/null > ~/a2a-agent-B.log 2>&1 &
echo $! > ~/a2a-agent-B.pid
```

---

## 三、验证更新成功

让 A 电脑发一条测试消息给你：

A 端执行：
```bash
HUB_HTTP=http://8.156.83.217:8086 TOKEN=tok-A-dev-2026-a2a python3 cli/ai_send.py send \
  --from computer-A --to computer-B --type echo --text "B 端更新验证"
```

**B 端 daemon 日志**应该看到：

```
[2026-xx-xx xx:xx:xx] 连接 Hub: ws://8.156.83.217:8086/ws/computer-B?token=xxx
✅ computer-B 已上线

📨 收到任务 (id=xxx) from computer-A
⚙️  处理任务: echo from computer-A
📝 已回包: id=xxx
📤 已发送: id=xxx
```

**A 端**会收到完整 result：

```
🎉 B 回包:
{
  "status": "completed",
  "output": {"echo": {"text": "B 端更新验证"}}
}
```

如果看到这些就成功了 ✅

---

## 四、回滚（如果出问题）

```bash
cd ~/Documents/a2a-mesh
git log --oneline -5     # 看 commit 历史
git reset --hard 67b807f  # 回到旧版本（不推荐，但紧急时可用）
# 然后重启 daemon
```

---

## 五、联系

更新过程中遇到问题，提供：
1. `git pull` 的完整输出
2. daemon 启动时的完整日志（`~/a2a-agent-B.log` 或 `/tmp/a2a-agent-B.log`）
3. `python3 --version` 输出
4. `nc -zv 8.156.83.217 8086` 输出

---

**最后更新**：2026-09-08  
**对应 commit**：`8f72d72`  
**项目地址**：https://github.com/136500201/AI-Agent-Comm