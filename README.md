# AI-Agent-Comm

> 跨电脑 AI Agent 协作框架 — 让多台电脑上的 AI Agent 像聊天一样互相协作

[![Status](https://img.shields.io/badge/status-MVP-yellow)]()
[![Python](https://img.shields.io/badge/python-3.8%2B-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

## 这是什么

一个**最小可用的多 Agent 通信框架**：

- **Hub Server**：阿里云 ECS 上跑的中央路由（WebSocket + SQLite）
- **Agent Daemon**：每台电脑一个常驻进程，保持长连接
- **CLI 工具**：命令行发消息/查历史

每台电脑在不同的网络（NAT/防火墙后面），都能互相通信。灵感来自 Google 的 [Agent2Agent (A2A) Protocol](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability)，但做了大幅简化。

## 架构

```
   电脑 A (开发)                       阿里云 ECS (Hub)                  电脑 B (评审)
   ┌──────────────┐                                                  ┌──────────────┐
   │ Claude Code  │                                                  │ Claude Code  │
   │      ▲       │                                                  │      ▲       │
   │      │       │                                                  │      │       │
   │  A-Agent     │                                                  │     B-Agent  │
   │  daemon ◄────┼────WSS────► ┌──────────────┐ ◄────WSS────────────┼────► daemon  │
   │  (Python)    │             │ Hub Server   │                      │   (Python)   │
   └──────────────┘             │ FastAPI+WS   │                      └──────────────┘
                                │ SQLite       │
                                │ Port 8086    │
                                └──────────────┘
```

## 5 分钟跑起来

### 1. 部署 Hub 到阿里云 ECS

```bash
# 上传代码
scp -P 2223 -r hub/ root@YOUR_SERVER:/AIProject/a2a-mesh/

# SSH 到 ECS
ssh -p 2223 root@YOUR_SERVER
cd /AIProject/a2a-mesh/hub
pip3.8 install -r requirements.txt

# 配环境变量（含 Token）
cat > /etc/a2a-mesh.env <<EOF
HUB_PORT=8086
HUB_DB_PATH=/AIProject/a2a-mesh/data/a2a_mesh.db
TOKEN_A=tok-A-CHANGE-ME
TOKEN_B=tok-B-CHANGE-ME
EOF
chmod 600 /etc/a2a-mesh.env

# 写 systemd
cat > /etc/systemd/system/a2a-mesh-hub.service <<EOF
[Unit]
Description=A2A Mesh Hub
After=network.target
[Service]
Type=simple
User=root
WorkingDirectory=/AIProject/a2a-mesh/hub
EnvironmentFile=/etc/a2a-mesh.env
ExecStart=/usr/bin/python3.8 /AIProject/a2a-mesh/hub/server.py
Restart=always
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload && systemctl enable --now a2a-mesh-hub
```

### 2. ECS 安全组放行 8086

阿里云控制台 → ECS → 安全组 → 入方向 → TCP:8086，仅放行你电脑的公网 IP。

### 3. 每台电脑跑 Agent

```bash
pip3 install -r agent/requirements.txt

# A 电脑
python3 agent/daemon.py --id computer-A --token tok-A-CHANGE-ME --hub ws://YOUR_SERVER:8086

# B 电脑
python3 agent/daemon.py --id computer-B --token tok-B-CHANGE-ME --hub ws://YOUR_SERVER:8086
```

### 4. 发送消息

```bash
export HUB_HTTP=http://YOUR_SERVER:8086
export TOKEN=tok-A-CHANGE-ME

# A 提需求给 B
python3 cli/ai_send.py send --from computer-A --to computer-B \
  --type requirement_clarification --text "我想做个用户积分系统"

# 查看历史
python3 cli/ai_send.py history computer-A --limit 20
```

## 消息协议（简化版 A2A）

```json
{
  "jsonrpc": "2.0",
  "id": "msg-xxx",
  "method": "tasks/send",
  "to": "computer-B",
  "params": {
    "task": {
      "type": "requirement_clarification",
      "input": {"text": "..."}
    }
  }
}
```

回包：
```json
{
  "jsonrpc": "2.0",
  "id": "msg-xxx",
  "result": {
    "status": "completed",
    "output": {"summary": "...", "questions": [...]}
  }
}
```

## 已验证场景

| 场景 | 状态 |
|------|------|
| 单机 A→A 自发自收 | ✅ 验证通过 |
| A↔B 跨电脑协作 | ✅ 验证通过（echo + requirement_clarification） |
| 需求澄清单轮任务 | ✅ 验证通过（A 发需求 → B 回 3 个问题） |
| 需求澄清多轮对话 | 🔲 待 mock 支持上下文 |
| 自动重连（断线重连） | ✅ 验证通过 |
| 离线消息补推（pending → 上线时拉取） | ✅ 验证通过 |

## Roadmap

- [x] Phase 1：Hub 部署 + WebSocket 路由
- [x] Phase 2：Agent Daemon + CLI
- [x] Phase 3：单机 A→A 全链路验证
- [x] Phase 4：B 电脑接入（已上线 A↔B）
- [x] Phase 5：端到端回包链路验证（含回包路由修复）
- [ ] Phase 5b：真实需求澄清多轮对话（需要 mock 支持上下文，或接入真 Claude）
- [ ] Phase 6：接入真实 Claude API（替换 mock）
- [ ] Phase 7：TLS + 限流 + 审计
- [ ] Phase 8：Web UI（任务看板 + 对话历史）

## 安全注意

- Bearer Token 通过环境变量注入，**不要写进代码**
- ECS 安全组**只放行你的电脑 IP**，不要 `0.0.0.0/0`
- 生产环境上 TLS（Let's Encrypt）+ 限流

## 踩过的坑（重要教训）

调试 A↔B 端到端通信时连踩 4 个隐藏 bug：

1. **Hub WS 转发未持久化**：收到 A 的任务后直接转发给 B，但没存 db。导致 B 回包时 Hub 查不到原消息的 frm
2. **Hub 收到 result 不转发**：原来只 `mark_delivered` 不推送给原发送方，A 永远收不到 result
3. **daemon 收到 result 当成任务处理**：result 消息没 `params.task` 字段，daemon 傻乎乎按空任务处理 → 产生空 result 循环风暴
4. **UNIQUE 约束失败 + 重复 mark_delivered**：修复 #1 后又踩这两个，需要 `INSERT OR IGNORE` + `AND status='pending'`
5. **离线消息不补推**：B 上线时 Hub 不会主动拉 pending，加 `push_pending_messages()` 在连接时触发

修复后链路：A 发任务 → Hub 持久化 → 转发 → B 处理 → B 发 result → Hub 查 frm → 转发 result 给 A。

详见 `docs/PITFALLS.md`（待补）

## License

MIT
