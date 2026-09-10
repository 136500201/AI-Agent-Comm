# B 端 DSH Harness 集成指南

> **场景**：B daemon 接入 DeepSeek Harness（dsh）—— 让 B 真能跑命令、读文件、写代码，不只是聊天。
>
> **前置**：B 电脑已经装了 dsh 并启动（`dsh web --port 3080 --host 127.0.0.1`）。
>
> **预计时间：5 分钟**

---

## 一、为什么升级

之前 daemon.py 收到 A 的任务后只能调 Claude API（或 mock）回文字。装上 dsh 后：

| 项 | 升级前 | 升级后 |
|---|---|---|
| 处理任务 | Claude API / mock | **dsh → MiniMax-M3** |
| 能跑命令 | ❌ | ✅ |
| 能读文件 | ❌ | ✅ |
| 能写代码 | ❌ | ✅ |
| daemon.py 优先级 | claude / mock | **dsh** (claude 退为备选) |

---

## 二、架构

```
A 电脑 → Hub ECS → B daemon.py → dsh (127.0.0.1:3080) → MiniMax-M3
                                              ↓
                                       真能跑 Bash/Read/Write
```

**关键约束**（dsh 设计）：
- dsh 只绑 `127.0.0.1`，daemon.py **必须和 dsh 同机**
- daemon.py 通过 HTTP (unary) + WebSocket (follow) 双协议调 dsh
- Cookie 认证（一次性 token URL → 30 天 JWT cookie）

---

## 三、升级步骤

### Step 1：拉最新代码

```bash
cd ~/Documents/a2a-mesh   # 或你之前 clone 的路径
git pull origin main
```

应该看到：
```
 agent/daemon.py      | 修改（增加 dsh 优先级）
 agent/dsh_client.py  | 新增（约 250 行）
 docs/HARNESS-INSTALL.md | 新增
 docs/HARNESS-INTEGRATION*.md | 集成参数文档
```

### Step 2：装 websockets（如果还没装）

dsh_client.py 依赖 `websockets`：

```bash
pip3 install websockets
# 或跟 requirements.txt 一起
pip3 install -r agent/requirements.txt
```

### Step 3：配环境变量

编辑 `~/.a2a-mesh.env`：

```bash
nano ~/.a2a-mesh.env
```

加这些（dsh 相关）：

```bash
# ============ DSH Harness ============
export HARNESS_BASE="http://127.0.0.1:3080"
export HARNESS_WS="ws://127.0.0.1:3080/api/remote.mux"
export HARNESS_COOKIE_JAR="$HOME/.dsh-daemon-cookies.txt"
export HARNESS_TOKEN_FILE="$HOME/dsh-token.txt"
export HARNESS_PROVIDER="anthropic"
export HARNESS_MODEL="MiniMax-M3"
export HARNESS_HTTP_TIMEOUT=30
export HARNESS_FOLLOW_TIMEOUT=300
```

让环境变量生效：
```bash
source ~/.a2a-mesh.env
```

### Step 4：确认 dsh 在跑 + cookie 准备好

```bash
# 1. 确认 dsh 进程
ps aux | grep "dsh web" | grep -v grep
# 应该看到 dsh web --port 3080

# 2. 确认端口监听
lsof -i :3080 | grep LISTEN
# 应该看到 127.0.0.1:3080

# 3. 确认 token 文件存在
ls -la ~/dsh-token.txt
# 如果不存在：跑 ~/bin/dsh-start.sh 启动 dsh，会自动写

# 4. 换 cookie（一次性 token → 30 天 JWT）
TOKEN_URL=$(cat ~/dsh-token.txt)
curl -c ~/.dsh-daemon-cookies.txt "$TOKEN_URL"

# 5. 验证 cookie 能用
curl -b ~/.dsh-daemon-cookies.txt \
  -X POST http://127.0.0.1:3080/api/session/list \
  -H "Content-Type: application/json" \
  -d '{"type":"client-request","rpcId":"test","method":"session/list","payload":{"args":{"_request":{}}}}'
```

应该返回：
```json
{"type":"server-response","rpcId":"test","result":{"ok":true,"value":{"sessions":[...]}}}
```

如果返回 `401` 或 `result.ok=false`，cookie 没换成功，回去检查 token URL。

### Step 5：重启 daemon

```bash
# 杀旧 daemon
kill $(cat ~/a2a-agent-B.pid)

# 启动新 daemon
source ~/.a2a-mesh.env
nohup python3 agent/daemon.py --id "$COMPUTER_ID" --token "$TOKEN" --hub "$HUB_URL" \
  < /dev/null > ~/a2a-agent-B.log 2>&1 &
echo $! > ~/a2a-agent-B.pid
```

**关键日志**（说明 dsh 已启用）：

```
[2026-xx-xx xx:xx:xx] ✅ DSH Harness 已启用 (model: MiniMax-M3)
[2026-xx-xx xx:xx:xx] 连接 Hub: ws://8.156.83.217:8086/ws/computer-B?token=xxx
✅ computer-B 已上线
```

如果只看到 `连接 Hub` 但**没有** `✅ DSH Harness 已启用` 这一行，说明 `HARNESS_BASE` 没读到，回去检查 Step 3。

---

## 四、验证 dsh 真响应

让 A 电脑发个测试任务。

A 端执行（cli/ai_send.py）：
```bash
HUB_HTTP=http://8.156.83.217:8086 TOKEN=tok-A-dev-2026-a2a python3 cli/ai_send.py send \
  --from computer-A --to computer-B \
  --type echo \
  --text "请用 dsh 列出当前目录下最大的 3 个文件"
```

**A 端收到的 result.output.reply** 应该是 dsh 实际跑命令后的输出（不是 mock 复读）。

**B 端 daemon 日志**：
```
⚙️  处理任务: echo from computer-A
📝 已回包: id=xxx
```

---

## 五、Cookie 过期处理

dsh 的 cookie **30 天有效**。过期后 A 发的任务会返回 `401 Unauthorized`。

**恢复流程**（需要重启 dsh 拿新 token）：
```bash
# 1. 重启 dsh（新 token 会写到 ~/dsh-token.txt）
~/bin/dsh-start.sh

# 2. 用新 token 换新 cookie
TOKEN_URL=$(cat ~/dsh-token.txt)
curl -c ~/.dsh-daemon-cookies.txt "$TOKEN_URL"

# 3. 重启 daemon 让它读到新 cookie（或者 daemon 启动时会自动读新文件）
kill $(cat ~/a2a-agent-B.pid)
source ~/.a2a-mesh.env
nohup python3 agent/daemon.py --id "$COMPUTER_ID" --token "$TOKEN" --hub "$HUB_URL" \
  < /dev/null > ~/a2a-agent-B.log 2>&1 &
echo $! > ~/a2a-agent-B.pid
```

⚠️ 当前 daemon 不会自动感知 cookie 过期（401 后直接报错）。后续可以做自动恢复。

---

## 六、常见问题

**Q：daemon 启动报 `ImportError: No module named 'websockets'`？**
A：Step 2 没装：
```bash
python3 -m pip install websockets
```

**Q：daemon 启动报 `TOKEN_FILE not found`？**
A：`~/dsh-token.txt` 不存在。先跑 `~/bin/dsh-start.sh`，让 dsh 把 token 写到那里。

**Q：任务一直卡住 / 超时？**
A：
1. 看 daemon 日志：`tail -f ~/a2a-agent-B.log`
2. 看 dsh 还在不在：`ps aux | grep dsh`
3. 直接 curl dsh 测试：`curl http://127.0.0.1:3080/`
4. 看 dsh 日志（位置取决于你怎么启动的，常见 `~/.dsh/logs/`）

**Q：怎么临时回退到 claude / mock？**
A：注释掉 `~/.a2a-mesh.env` 里的 HARNESS_BASE 那行，重启 daemon。

**Q：能同时用 dsh 和 claude 吗？**
A：可以。daemon 优先级是 dsh > claude > mock。dsh 出错时会自动报错（不降级），如果想 dsh 失败时降级到 claude，需要改 daemon 代码。

---

## 七、参考文档

- [HARNESS-INTEGRATION.md](./HARNESS-INTEGRATION.md) — A 电脑对 dsh 接口的需求清单（已废弃，被本文件取代）
- [HARNESS-INTEGRATION-ANSWERS.md](./HARNESS-INTEGRATION-ANSWERS.md) — B 工程师对接口的答复
- [B-DEPLOY.md](./B-DEPLOY.md) — 首次部署指南
- [B-UPDATE.md](./B-UPDATE.md) — daemon 代码更新流程
- [B-CLAUDE-UPGRADE.md](./B-CLAUDE-UPGRADE.md) — Claude API 升级（dsh 的备选方案）

---

**最后更新**：2026-09-08
**对应 Phase**：Phase 7 - DSH Harness 接入
**项目地址**：https://github.com/136500201/AI-Agent-Comm
