"""
A2A Mesh - Hub Server
中央消息路由 + WebSocket Server + SQLite 持久化
"""
import asyncio
import json
import sqlite3
import uuid
import os
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, List

# ============ 配置 ============
HUB_PORT = int(os.getenv("HUB_PORT", 8086))
DB_PATH = os.getenv("HUB_DB_PATH", "./a2a_mesh.db")
TOKEN_A = os.getenv("TOKEN_A", "tok-A-dev-2026")
TOKEN_B = os.getenv("TOKEN_B", "tok-B-dev-2026")
TOKEN_MAP = {TOKEN_A: "computer-A", TOKEN_B: "computer-B"}

# ============ 数据库 ============
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        method TEXT,
        frm TEXT NOT NULL,
        too TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        reply_to TEXT,
        task_type TEXT,
        created_at TEXT NOT NULL,
        delivered_at TEXT
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_too_status ON messages(too, status)')
    conn.commit()
    conn.close()

init_db()

# ============ 在线客户端管理 ============
class ConnectionManager:
    def __init__(self):
        # 每个 computer_id 支持多个连接（list 模式），消息广播给所有
        self.active: Dict[str, list] = {}

    async def connect(self, computer_id: str, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(computer_id, []).append(ws)
        print(f"[{datetime.now().isoformat()}] {computer_id} connected (共 {len(self.active[computer_id])} 个连接)")

    def disconnect(self, computer_id: str, ws: WebSocket):
        if computer_id in self.active and ws in self.active[computer_id]:
            self.active[computer_id].remove(ws)
            print(f"[{datetime.now().isoformat()}] {computer_id} 一个连接断开 (剩余 {len(self.active[computer_id])})")
            if not self.active[computer_id]:
                del self.active[computer_id]

    async def send(self, computer_id: str, message: str) -> bool:
        """广播给该 computer_id 的所有连接"""
        conns = self.active.get(computer_id, [])
        if not conns:
            return False
        for ws in conns[:]:  # 复制一份避免迭代时修改
            try:
                await ws.send_text(message)
            except Exception:
                # 失效连接：清理
                if ws in self.active.get(computer_id, []):
                    self.active[computer_id].remove(ws)
        return True

manager = ConnectionManager()

# ============ 消息持久化 ============
def save_message(msg: dict, frm: str, too: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    msg_id = msg.get("id") or str(uuid.uuid4())
    params = msg.get("params", {})
    task = params.get("task", {}) if isinstance(params, dict) else {}
    task_type = task.get("type", "unknown") if isinstance(task, dict) else "unknown"
    c.execute('''INSERT OR IGNORE INTO messages (id, method, frm, too, payload, status, reply_to, task_type, created_at)
                 VALUES (?,?,?,?,?,?,?,?,?)''',
              (msg_id, msg.get("method", "msg"), frm, too, json.dumps(msg, ensure_ascii=False),
               "pending", msg.get("reply_to"), task_type, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return msg_id

def mark_delivered(msg_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 只标记仍然 pending 的（避免回包乱标）
    c.execute('UPDATE messages SET status=?, delivered_at=? WHERE id=? AND status=?',
              ("delivered", datetime.utcnow().isoformat(), msg_id, "pending"))
    conn.commit()
    conn.close()

async def push_pending_messages(computer_id: str):
    """客户端上线时，把 pending 消息推给它"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, payload FROM messages WHERE too=? AND status=? LIMIT 50',
              (computer_id, "pending"))
    rows = c.fetchall()
    conn.close()
    for msg_id, payload in rows:
        try:
            await manager.send(computer_id, payload)
            mark_delivered(msg_id)
            print(f"[{computer_id}] 重连后补推 pending id={msg_id}")
        except Exception as e:
            print(f"[{computer_id}] 补推失败 id={msg_id}: {e}")

# ============ FastAPI App ============
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print(f"Hub started on port {HUB_PORT}, DB: {DB_PATH}")
    yield

app = FastAPI(title="A2A Mesh Hub", lifespan=lifespan)

@app.get("/")
def root():
    return {
        "service": "a2a-mesh-hub",
        "version": "0.1.0",
        "online": list(manager.active.keys()),
        "port": HUB_PORT
    }

@app.get("/health")
def health():
    return {"status": "ok", "online": list(manager.active.keys())}

class MessageIn(BaseModel):
    frm: str
    too: str
    payload: dict
    method: Optional[str] = "tasks/send"

@app.post("/api/send")
async def http_send(msg: MessageIn, authorization: Optional[str] = Header(None)):
    """HTTP 发送接口（用于 CLI）"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    sender = TOKEN_MAP.get(token)
    if not sender:
        raise HTTPException(403, "invalid token")
    if msg.frm != sender:
        raise HTTPException(403, f"token mismatch: token says {sender}, payload says {msg.frm}")

    rpc_msg = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": msg.method,
        "params": msg.payload,
    }
    msg_id = save_message(rpc_msg, msg.frm, msg.too)

    # 立即尝试通过 WebSocket 推送给目标（如果在线）
    payload_with_meta = dict(rpc_msg)
    payload_with_meta["from"] = msg.frm
    payload_with_meta["to"] = msg.too
    delivered = await manager.send(msg.too, json.dumps(payload_with_meta, ensure_ascii=False))
    if delivered:
        mark_delivered(msg_id)
        return {"id": msg_id, "status": "delivered", "to": msg.too}
    else:
        return {"id": msg_id, "status": "queued", "to": msg.too, "reason": f"{msg.too} offline"}

@app.get("/api/history/{computer_id}")
def history(computer_id: str, limit: int = 50, authorization: Optional[str] = Header(None)):
    """查询历史消息"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    caller = TOKEN_MAP.get(token)
    if not caller or caller != computer_id:
        raise HTTPException(403, "can only query own history")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT id, method, frm, too, payload, status, task_type, created_at, delivered_at
                 FROM messages WHERE frm=? OR too=? ORDER BY created_at DESC LIMIT ?''',
              (computer_id, computer_id, limit))
    rows = c.fetchall()
    conn.close()
    return {
        "computer_id": computer_id,
        "count": len(rows),
        "messages": [
            {
                "id": r[0], "method": r[1], "from": r[2], "to": r[3],
                "payload": json.loads(r[4]), "status": r[5], "task_type": r[6],
                "created_at": r[7], "delivered_at": r[8]
            } for r in rows
        ]
    }

@app.websocket("/ws/{computer_id}")
async def websocket_endpoint(websocket: WebSocket, computer_id: str, token: str = ""):
    """WebSocket 长连接入口"""
    # Token 校验（从 query string 传）
    sender = TOKEN_MAP.get(token)
    if not sender or sender != computer_id:
        await websocket.close(code=4001, reason="invalid token")
        return

    await manager.connect(computer_id, websocket)

    # 上线时拉取待发消息（避免对方下线时发的任务被"吞"）
    await push_pending_messages(computer_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "invalid json"}))
                continue

            # 收到的消息可能是回包 (result) 或新消息
            if "result" in msg or "error" in msg:
                # 回包：查原消息发送方，转发回去 + 标记交付
                reply_to = msg.get("id") or msg.get("reply_to")
                if reply_to:
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute('SELECT frm FROM messages WHERE id=?', (reply_to,))
                    row = c.fetchone()
                    conn.close()
                    if row:
                        original_sender = row[0]
                        await manager.send(original_sender, json.dumps(msg, ensure_ascii=False))
                        mark_delivered(reply_to)
                        print(f"[{computer_id}] reply → {original_sender}")
                    else:
                        print(f"[{computer_id}] reply_to={reply_to} 原消息未找到")
                else:
                    print(f"[{computer_id}] reply without reply_to: {msg.get('result', msg.get('error'))}")
            else:
                # 新消息：先持久化（必须！回包时要查原消息的 frm），再转发
                target = msg.get("to") or (msg.get("params", {}) or {}).get("to")
                if not target:
                    await websocket.send_text(json.dumps({"error": "missing 'to' field"}))
                    continue
                msg["from"] = computer_id  # 强制覆盖
                # 持久化（用消息原 id，没有就生成）
                msg_id = msg.get("id") or str(uuid.uuid4())
                msg["id"] = msg_id
                save_message(msg, computer_id, target)
                delivered = await manager.send(target, json.dumps(msg, ensure_ascii=False))
                if delivered:
                    mark_delivered(msg_id)
                    await websocket.send_text(json.dumps({"ack": True, "id": msg_id}))
                else:
                    # 离线：消息已 save_message 持久化，状态保持 pending
                    await websocket.send_text(json.dumps({
                        "ack": False, "id": msg_id,
                        "reason": f"{target} offline, queued"
                    }))
    except WebSocketDisconnect:
        manager.disconnect(computer_id, websocket)
    except Exception as e:
        print(f"[{computer_id}] error: {e}")
        manager.disconnect(computer_id, websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=HUB_PORT, log_level="info")
