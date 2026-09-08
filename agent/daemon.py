"""
A2A Mesh - Agent Daemon (简化版)
不依赖 claude-agent-sdk，先跑通通信。
AI 处理逻辑用本地 mock（Phase 5 再接真实 Claude）。
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

inbox: asyncio.Queue = None
outbox: asyncio.Queue = None

# ============ 任务处理（mock 版）============
async def handle_task(task: dict) -> dict:
    """处理任务 - MVP 版本直接 mock 回包"""
    task_type = task.get("type", "unknown")
    task_input = task.get("input", {})

    # Mock 响应：真实场景会调 Claude API
    if task_type == "requirement_clarification":
        requirement = task_input.get("requirement") or task_input.get("text", "")
        mock_response = {
            "status": "completed",
            "output": {
                "summary": f"B 电脑收到需求: {requirement[:50]}...",
                "questions": [
                    "Q1: 这个需求的目标用户是谁？",
                    "Q2: 期望什么时候完成？",
                    "Q3: 有什么参考实现吗？"
                ],
                "note": "（mock 响应，Phase 5 接真实 Claude）"
            }
        }
    elif task_type == "echo":
        mock_response = {
            "status": "completed",
            "output": {"echo": task_input}
        }
    else:
        mock_response = {
            "status": "completed",
            "output": {"echo": task_input, "task_type": task_type}
        }

    return mock_response

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
                    print(f"🔍 RAW 收到: {raw[:200]}")
                    try:
                        msg = json.loads(raw)
                        if "ack" in msg:
                            print(f"📬 ACK: {msg}")
                            continue
                        if "error" in msg:
                            print(f"❌ ERROR: {msg}")
                            continue
                        # 真实任务消息
                        print(f"\n📨 收到任务 (id={msg.get('id', '?')})")
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
