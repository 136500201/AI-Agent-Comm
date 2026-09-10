# A2A Mesh ↔ DeepSeek Harness 集成需求清单

> **背景**：B 电脑已经启动了一个 DeepSeek Harness Agent（以下简称 "Harness"）作为长期运行服务。
> A 电脑的 daemon 想接收 A 电脑发来的任务，转交给 Harness 处理，再把 Harness 的回复发回 A。
>
> **目的**：A↔B 通信从「盲眼聊天机器人」升级为「真 Agent 协作」——B 能真跑命令、读文件、写代码。
>
> **目标读者**：B 电脑的运维 / 部署 Harness 的工程师。

---

## 一、整体架构（要确认的事实）

```
┌──────────────┐         ┌──────────┐         ┌──────────────────┐
│ A 电脑       │  WS →   │ Hub ECS  │  WS →   │ B daemon.py      │
│ (Claude Code)│  ← WS   │ (8.156.  │  ← WS   │   ↓              │
│              │         │  83.217) │         │ spawn/forward    │
│              │         │          │         │   ↓              │
│              │         │          │         │ DeepSeek Harness │
│              │         │          │         │ (long-running)   │
└──────────────┘         └──────────┘         └──────────────────┘
```

✅ 已确认：
- Harness 是 long-running 服务（在 B 电脑一直跑）
- daemon.py 通过某种 IPC 方式调 Harness

❓ 待确认（请 B 工程师回答下面 Q1~Q10）

---

## 二、Question 清单（A 电脑想知道的）

### Q1：访问方式（最重要）

daemon 怎么调到 Harness？三选一（或其它）：

- **(a) HTTP/REST API**：daemon `POST` 请求，Harness 返回 JSON
- **(b) stdio / 子进程**：daemon `subprocess.run([...])`，Harness 输出到 stdout
- **(c) WebSocket**：daemon 跟 Harness 起 WS 连接
- **(d) gRPC**：daemon 通过 protobuf 调用
- **(e) 其它**：__________________

### Q2：端点 / 命令

如果是 HTTP：
```
完整 URL：________________________________________
端口：________
路径前缀：________（如有）
```

如果是 stdio / CLI：
```
完整命令行：________________________________________
（例：deepseek agent run --prompt "..."）
```

如果是 WebSocket：
```
URL：ws://localhost:______/________
```

### Q3：认证

需要 token / API Key 吗？
- ✅ 需要：Header 名称 ______，值：______
- ❌ 不需要（本地 socket 可信）

### Q4：请求格式（daemon 怎么发任务）

给 Harness 发什么？请给一个**最小完整示例**，比如：

**JSON 请求**（如果是 HTTP/WS）：
```json
{
  ???: "???",
  ???: "???"
}
```

**命令行参数**（如果是 CLI）：
```bash
????? "????"
```

### Q5：响应格式（Harness 怎么回结果）

Harness 处理完返回什么？请给一个**最小完整示例**：

**JSON 响应**（如果是 HTTP/WS）：
```json
{
  ???: "???",
  ???: "???"
}
```

**stdout 输出**（如果是 CLI）：
```
?????
```

### Q6：超时

单次任务 Harness 最长跑多久？
- 建议值：______ 秒（或"无限制"）

### Q7：同步 vs 异步

- **同步**：daemon 发请求 → 等 Harness 跑完 → 一次性返回结果
- **异步**：daemon 发请求 → Harness 返回 task_id → daemon 轮询 / 接收回调

实际是哪种？______

### Q8：是否支持流式输出

Harness 处理过程中能不能一边跑一边输出（streaming），还是必须等全部完成？
- 支持 streaming（Server-Sent Events / chunked response）
- 必须等全部完成再返回

### Q9：会话 / 上下文

Harness 是否支持多轮对话上下文？
- ✅ 支持（请给 session_id 字段名）
- ❌ 不支持（每次调用是无状态的）
- 其它：______

### Q10：服务健康检查

daemon 怎么知道 Harness 还活着？
- HTTP `/health` 端点？
- 命令行 `??? health`？
- 其它？

---

## 三、daemon.py 集成方式（preview）

确认 Q1~Q10 后，daemon.py 大概这么改：

```python
# 伪代码（具体实现取决于 Q1~Q10 的答案）
async def call_harness(task: dict, from_id: str) -> dict:
    """把 A 任务转给 Harness，等结果"""
    if HARNESS_MODE == "http":
        async with httpx.AsyncClient() as client:
            r = await client.post(
                HARNESS_URL,
                json={"prompt": _build_prompt(task), "from": from_id},
                headers={"Authorization": f"Bearer {HARNESS_TOKEN}"} if HARNESS_TOKEN else None,
                timeout=HARNESS_TIMEOUT
            )
            return r.json()

    elif HARNESS_MODE == "stdio":
        proc = await asyncio.create_subprocess_exec(
            *HARNESS_CMD, _build_prompt(task),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return {"text": stdout.decode(), "stderr": stderr.decode()}
```

配置走环境变量：
```bash
# ~/.a2a-mesh.env
export HARNESS_MODE="http"             # 或 stdio / ws
export HARNESS_URL="http://127.0.0.1:XXX"
export HARNESS_TOKEN="..."             # 可选
export HARNESS_TIMEOUT=120
export HARNESS_PROMPT_FIELD="prompt"   # 根据 Q4
export HARNESS_RESULT_FIELD="result"   # 根据 Q5
```

---

## 四、B 工程师请做的事

1. **回答 Q1~Q10**（直接编辑本文档，把 `???` 替换成实际值）
2. **测试 Harness 能正常接收任务**（用 curl / 手动命令行）
3. **把更新后的文档 commit 到 GitHub 或 push 到 ECS**：
   ```bash
   # 选项 A：放到 ECS /AIProject/a2a-mesh/docs/
   scp HARNESS-INTEGRATION.md user@ecs:/AIProject/a2a-mesh/docs/

   # 选项 B：直接 commit 到 GitHub
   cd ~/Documents/a2a-mesh
   git add docs/HARNESS-INTEGRATION.md
   git commit -m "docs: DeepSeek Harness 集成参数"
   git push origin main
   ```

A 电脑拿到答案后，开始改 daemon.py + 测试。

---

**创建时间**：2026-09-08
**创建人**：A 电脑（我）
**等待**：B 电脑运维工程师填 Q1~Q10
