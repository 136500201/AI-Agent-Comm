# A2A Mesh 部署指南

## 一、架构

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

## 二、Hub Server 部署（阿里云 ECS）

### 1. 上传代码

```bash
# 老电脑上
rsync -avz -e "ssh -p 2223" \
  "/Users/liuzhitong/Documents/个人/AI创业/03-共享工具库/a2a-mesh/hub/" \
  root@8.156.83.217:/AIProject/a2a-mesh/hub/
```

### 2. 安装依赖

```bash
ssh -p 2223 root@8.156.83.217
cd /AIProject/a2a-mesh/hub
pip3 install -r requirements.txt
```

### 3. 配置环境变量

```bash
cat > /etc/a2a-mesh.env <<'EOF'
HUB_PORT=8086
HUB_DB_PATH=/AIProject/a2a-mesh/data/a2a_mesh.db
TOKEN_A=tok-A-xxx-2026
TOKEN_B=tok-B-xxx-2026
EOF
chmod 600 /etc/a2a-mesh.env
```

### 4. 开放 ECS 端口

```bash
# 安全组放行 8086
# 阿里云控制台 → ECS → 安全组 → 入方向 → 添加入站规则 TCP:8086 0.0.0.0/0
```

### 5. systemd 服务

```bash
cat > /etc/systemd/system/a2a-mesh-hub.service <<'EOF'
[Unit]
Description=A2A Mesh Hub Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/AIProject/a2a-mesh/hub
EnvironmentFile=/etc/a2a-mesh.env
ExecStart=/usr/bin/python3 server.py
Restart=always
RestartSec=5
StandardOutput=append:/var/log/a2a-mesh-hub.log
StandardError=append:/var/log/a2a-mesh-hub.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable a2a-mesh-hub
systemctl start a2a-mesh-hub
systemctl status a2a-mesh-hub
```

### 6. 验证

```bash
# 健康检查
curl http://127.0.0.1:8086/health
# 期望: {"status":"ok","online":[]}

# 外网测试（从任意电脑）
curl http://8.156.83.217:8086/health
```

## 三、Agent Daemon 部署（每台电脑）

### 1. 安装

```bash
# 每台电脑
pip3 install websockets requests claude-agent-sdk
```

### 2. 配置环境变量

```bash
# A 电脑
cat > ~/.a2a-mesh.env <<'EOF'
HUB_URL=wss://8.156.83.217:8086
COMPUTER_ID=computer-A
TOKEN=tok-A-xxx-2026
EOF
source ~/.a2a-mesh.env
```

### 3. 启动

```bash
# 前台跑（开发）
python3 agent/daemon.py --id computer-A --token tok-A-xxx-2026

# 后台跑（生产）
nohup python3 agent/daemon.py --id computer-A --token tok-A-xxx-2026 \
  > /tmp/a2a-agent-A.log 2>&1 &
```

## 四、CLI 使用

```bash
# A 提需求给 B
export TOKEN=tok-A-xxx-2026
python3 cli/ai_send.py send --from computer-A --to computer-B \
  --type requirement_clarification \
  --text "我想做一个用户积分系统"

# 查看历史
python3 cli/ai_send.py history computer-A --limit 20
```

## 五、消息协议

### request（任务）

```json
{
  "jsonrpc": "2.0",
  "id": "msg-xxx",
  "method": "tasks/send",
  "to": "computer-B",
  "params": {
    "task": {
      "type": "requirement_clarification",
      "input": {"requirement": "..."}
    }
  }
}
```

### reply（回包）

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

## 六、安全

- Bearer Token 放在 `chmod 600` 的环境变量文件
- WSS 走 TLS（暂用自签，生产建议上 Let's Encrypt）
- fail2ban 已启用，防止 Agent 被暴力破解
