"""
A2A Mesh - Agent Daemon
AI 处理调真 Claude API (Phase 6)
如未配置 ANTHROPIC_API_KEY 则回退到 mock。
"""
import asyncio
import json
import os
import sys
import argparse
from datetime import datetime
from typing import Optional
import websockets

# ============ 配置 ============
HUB_URL = os.getenv("HUB_URL", "ws://127.0.0.1:8086")
COMPUTER_ID = os.getenv("COMPUTER_ID", "computer-A")
TOKEN = os.getenv("TOKEN", "tok-A-dev-2026-a2a")
USE_CLAUDE = bool(os.getenv("ANTHROPIC_API_KEY"))

inbox: asyncio.Queue = None
outbox: asyncio.Queue = None

# 延迟导入 Claude 客户端（避免无 anthropic 包时报错）
claude_client = None
if USE_CLAUDE:
    try:
        from claude_client import call_claude, _build_task_prompt
        claude_client = call_claude
        print(f"[{datetime.now().isoformat()}] ✅ Claude API 已启用 (model: claude-sonnet-4-5)")
    except ImportError as e:
        print(f"⚠️ 无法 import claude_client: {e}，回退到 mock")
        USE_CLAUDE = False

# ============ 任务处理 ============
async def handle_task(task: dict, from_id: str = "unknown") -> dict:
    """处理任务 - 优先调真 Claude，无 API key 时回退 mock"""
    task_type = task.get("type", "unknown")
    task_input = task.get("input", {})

    # 真 Claude 处理
    if USE_CLAUDE and claude_client:
        prompt = _build_task_prompt(task)
        result = await claude_client(prompt, from_id=from_id, task_type=task_type)

        if "error" in result:
            return {
                "status": "error",
                "output": {
                    "error": result["error"],
                    "hint": result.get("hint", ""),
                    "task_type": task_type,
                }
            }

        return {
            "status": "completed",
            "output": {
                "reply": result["text"],
                "task_type": task_type,
                "model": result.get("model"),
                "tokens": result.get("usage"),
            }
        }

    # Mock 回退
    if task_type == "requirement_clarification":
        requirement = task_input.get("requirement") or task_input.get("text", "")
        return {
            "status": "completed",
            "output": {
                "summary": f"B 收到需求: {requirement[:50]}...",
                "questions": [
                    "Q1: 目标用户是谁？",
                    "Q2: 期望什么时候完成？",
                    "Q3: 有什么参考实现吗？"
                ],
                "note": "（mock，设置 ANTHROPIC_API_KEY 启用真 Claude）"
            }
        }
    elif task_type == "echo":
        return {"status": "completed", "output": {"echo": task_input}}
    else:
        return {"status": "completed", "output": {"echo": task_input, "task_type": task_type}}

# ============ 长连接 + 断线重连 ============
async def connect_and_listen():
    url = f"{HUB_URL}/ws/{COMPUTER_ID}?token={TOKEN}"
    while True:
        try:
            print(f"[{datetime.now().isoformat()}] 连接 Hub: {url}")
            async with websockets.connect(url, ping_interval=30) as ws:
                print(f"✅ {COMPUTER_ID} 已上线")

                send_task = asyncio.create_task(sender(ws))

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if "ack" in msg:
                            print(f"📬 ACK: {msg}")
                            continue
                        if "error" in msg:
                            print(f"❌ ERROR: {msg}")
                            continue
                        # 回包（不是新任务，不进 inbox）
                        if "result" in msg or "reply_to" in msg:
                            print(f"📩 收到回包: id={msg.get('id')} result={msg.get('result')}")
                            continue
                        # 真实任务消息
                        print(f"\n📨 收到任务 (id={msg.get('id', '?')}) from {msg.get('from', '?')}")
                        await inbox.put(msg)
                    except json.JSONDecodeError:
                        print(f"⚠️  非 JSON: {raw}")

                send_task.cancel()

        except Exception as e:
            print(f"❌ 连接失败: {e}, 5秒后重连...")
            await asyncio.sleep(5)

# ============ 发送协程 ============
async def sender(ws):
    while True:
        msg = await outbox.get()
        try:
            await ws.send(json.dumps(msg, ensure_ascii=False))
            print(f"📤 已发送: id={msg.get('id', '?')} to={msg.get('to', '?')}")
        except Exception as e:
            print(f"❌ 发送失败: {e}")
            await outbox.put(msg)
            break

# ============ 任务处理循环 ============
async def task_processor():
    while True:
        msg = await inbox.get()
        task = (msg.get("params") or {}).get("task") or {}
        sender_id = msg.get("from")
        msg_id = msg.get("id")

        print(f"⚙️  处理任务: {task.get('type', 'unknown')} from {sender_id}")

        result = await handle_task(task)

        reply = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "reply_to": msg_id,
            "result": result,
        }
        await outbox.put(reply)
        print(f"📝 已回包: id={msg_id}")

# ============ CLI 输入 ============
async def cli_input():
    print("\n" + "="*60)
    print(f"A2A Mesh Agent - {COMPUTER_ID}")
    print("="*60)
    print("命令:")
    print("  send <to> <task_type> <text>")
    print("  list")
    print("  quit")
    print("="*60 + "\n")

    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, input, f"[{COMPUTER_ID}]> ")
        except (EOFError, KeyboardInterrupt):
            return
        except Exception:
            # stdin 不可用（后台模式），跳过 CLI 输入
            await asyncio.sleep(1)
            continue
        line = line.strip()
        if not line:
            continue
        if line == "quit":
            os._exit(0)
        if line == "list":
            print(f"inbox 队列: {inbox.qsize()} 条未处理")
            continue
        if line.startswith("send "):
            parts = line.split(None, 3)
            if len(parts) < 4:
                print("用法: send <to> <task_type> <text>")
                continue
            _, to, task_type, text = parts
            msg = {
                "jsonrpc": "2.0",
                "id": f"msg-{datetime.now().timestamp()}",
                "method": "tasks/send",
                "to": to,
                "params": {"task": {"type": task_type, "input": {"text": text}}},
            }
            await outbox.put(msg)
            continue

# ============ Main ============
async def main():
    global inbox, outbox
    inbox = asyncio.Queue()
    outbox = asyncio.Queue()
    await asyncio.gather(
        connect_and_listen(),
        task_processor(),
        cli_input(),
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", default=COMPUTER_ID)
    parser.add_argument("--hub", default=HUB_URL)
    parser.add_argument("--token", default=TOKEN)
    args = parser.parse_args()

    COMPUTER_ID = args.id
    HUB_URL = args.hub
    TOKEN = args.token

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 bye")
