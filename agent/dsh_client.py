"""
A2A Mesh - DSH (DeepSeek Harness) Client
通过 dsh web (port 3080) 调用 MiniMax-M3 推理服务，支持多轮对话上下文。

基于 B 工程师提供的接口文档 + 参考客户端实现：
- 4 步：session/create → selectModel → prompt → follow (WS)
- prompt 异步，立刻返回，答案从 WS follow 流取
- Cookie 认证（一次性 token URL → 30 天 JWT）
- dsh 必须与 daemon.py 同机（仅绑 127.0.0.1）

环境变量：
- HARNESS_BASE：HTTP 端点，默认 http://127.0.0.1:3080
- HARNESS_WS：WS 端点，默认 ws://127.0.0.1:3080/api/remote.mux
- HARNESS_COOKIE_JAR：cookie 持久化路径
- HARNESS_TOKEN_FILE：一次性 token URL 文件路径
- HARNESS_PROVIDER：模型 provider，默认 anthropic
- HARNESS_MODEL：模型名，默认 MiniMax-M3
- HARNESS_HTTP_TIMEOUT：HTTP 超时秒，默认 30
- HARNESS_FOLLOW_TIMEOUT：WS follow 超时秒，默认 300
"""
import os
import json
import asyncio
import uuid
import time
import http.cookiejar
import urllib.request
import urllib.error
import websockets


# ============ 配置 ============
BASE = os.getenv("HARNESS_BASE", "http://127.0.0.1:3080")
WS_URL = os.getenv("HARNESS_WS", "ws://127.0.0.1:3080/api/remote.mux")
COOKIE_JAR = os.getenv("HARNESS_COOKIE_JAR", os.path.expanduser("~/.dsh-daemon-cookies.txt"))
TOKEN_FILE = os.getenv("HARNESS_TOKEN_FILE", os.path.expanduser("~/dsh-token.txt"))
PROVIDER = os.getenv("HARNESS_PROVIDER", "anthropic")
MODEL = os.getenv("HARNESS_MODEL", "MiniMax-M3")
HTTP_TIMEOUT = int(os.getenv("HARNESS_HTTP_TIMEOUT", "30"))
FOLLOW_TIMEOUT = int(os.getenv("HARNESS_FOLLOW_TIMEOUT", "300"))


# ============ Cookie 管理 ============
def _read_cookies_dict(path: str) -> dict:
    """读 curl netscape 格式 cookie jar → {name: value}"""
    if not os.path.exists(path):
        return {}
    cookies = {}
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            elif line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    return cookies


def _cookie_header(cookies: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _refresh_cookies() -> dict:
    """用一次性 token URL 换新 cookie，写到 jar"""
    if not os.path.exists(TOKEN_FILE):
        raise RuntimeError(
            f"TOKEN_FILE not found: {TOKEN_FILE}\n"
            f"B 电脑先跑 ~/bin/dsh-start.sh，token 会写到 {TOKEN_FILE}"
        )
    with open(TOKEN_FILE) as f:
        token_url = f.read().strip()
    if not token_url.startswith("http"):
        raise RuntimeError(f"TOKEN_FILE 内容不像 URL: {token_url[:80]}")

    cj = http.cookiejar.MozillaCookieJar(COOKIE_JAR)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.open(token_url, timeout=HTTP_TIMEOUT)
    cj.save(ignore_discard=True, ignore_expires=True)
    return _read_cookies_dict(COOKIE_JAR)


def _get_cookies() -> tuple:
    """拿 cookies，没有就 refresh。返回 (cookies_dict, cookie_header)"""
    cookies = _read_cookies_dict(COOKIE_JAR)
    if not cookies:
        cookies = _refresh_cookies()
    return cookies, _cookie_header(cookies)


# ============ HTTP RPC ============
def _rpc(endpoint: str, args: dict, cookie_header: str) -> dict:
    """HTTP unary 调用 dsh"""
    body = {
        "type": "client-request",
        "rpcId": str(uuid.uuid4()),
        "method": endpoint,
        "payload": {"args": args},
    }
    req = urllib.request.Request(
        f"{BASE}/api/{endpoint}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Cookie": cookie_header},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError(
                f"401 Unauthorized (cookie 过期，需要重启 dsh 拿新 token): "
                f"{e.read().decode()[:200]}"
            )
        raise
    result = out.get("result", {})
    if not result.get("ok"):
        raise RuntimeError(f"{endpoint} 失败: {result.get('error')}")
    return result.get("value", {})


# ============ Prompt 构建 ============
def _build_task_prompt(task: dict) -> str:
    """把 task 转换成 dsh prompt"""
    task_type = task.get("type", "unknown")
    task_input = task.get("input", {})

    if task_type == "requirement_clarification":
        req = task_input.get("requirement") or task_input.get("text", "")
        ctx = task_input.get("context", "")
        prompt = (
            f"需求澄清任务：\n\n需求：{req}\n\n背景：{ctx}\n\n"
            f"请分析这个需求是否清晰，列出还需要澄清的关键问题（如果有），"
            f"以及你的初步理解。"
        )
    elif task_type == "code_review":
        code = task_input.get("code", "")
        diff = task_input.get("diff", "")
        prompt = (
            f"代码评审任务：\n\n代码：\n```\n{code or diff}\n```\n\n"
            f"请评审这段代码，指出：1)潜在 bug 2)性能问题 3)可读性 "
            f"4)安全风险 5)改进建议。"
        )
    elif task_type == "echo":
        text = task_input.get("text", "")
        prompt = f"请用一句话回应（不要重复原文，要有自己的理解）：{text}"
    elif task_type == "test_feedback":
        bugs = task_input.get("bugs", [])
        verdict = task_input.get("verdict", "")
        prompt = f"QA 测试反馈：\n\n判定：{verdict}\n\n发现的Bug列表：\n"
        for i, b in enumerate(bugs, 1):
            prompt += f"{i}. {b}\n"
        prompt += "\n请根据这些反馈制定修复计划，给出每个 Bug 的修复方案。"
    else:
        prompt = (
            f"任务类型：{task_type}\n\n输入：\n"
            f"{json.dumps(task_input, ensure_ascii=False, indent=2)}"
        )
    return prompt


# ============ 会话管理 ============
# key = "{from_id}::{task_type}", value = {"sessionId": str, "created": float}
_sessions: dict = {}


def _get_session_id(from_id: str, task_type: str) -> str | None:
    key = f"{from_id}::{task_type}"
    return _sessions.get(key, {}).get("sessionId")


def _set_session_id(from_id: str, task_type: str, sid: str):
    key = f"{from_id}::{task_type}"
    _sessions[key] = {"sessionId": sid, "created": time.time()}


# ============ Follow 事件解析 ============
def _extract_assistant_text(event_value: dict) -> str:
    """从 follow 事件里尽可能提取 assistant 的最新文本。

    dsh 事件结构（实测以实测为准）：
    - {"type": "snapshot", "records": [...]}：全量历史，最后一条可能是 assistant
    - {"type": "record-added", "record": {...}}：新增消息
    - {"type": "record-updated", "record": {...}}：增量更新（流式文本）
    """
    if not isinstance(event_value, dict):
        return ""

    # snapshot：找最后一条 assistant
    if event_value.get("type") == "snapshot":
        records = event_value.get("records", [])
        for r in reversed(records):
            if r.get("role") == "assistant" or r.get("type") == "assistant":
                return _extract_text_from_content(r.get("content", []))

    # record-added / record-updated：直接拿 content
    for key in ("record", "data", "record-added", "record-updated"):
        v = event_value.get(key)
        if isinstance(v, dict) and (
            v.get("role") == "assistant" or v.get("type") == "assistant"
        ):
            return _extract_text_from_content(v.get("content", []))

    # 兜底：value.content 是文本
    content = event_value.get("content")
    if isinstance(content, str):
        return content

    return ""


def _extract_text_from_content(content) -> str:
    """从 message.content 提取纯文本"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for c in content:
            if isinstance(c, dict):
                if c.get("type") == "text" and isinstance(c.get("text"), str):
                    texts.append(c["text"])
                elif "text" in c and isinstance(c["text"], str):
                    texts.append(c["text"])
        return "\n".join(t for t in texts if t)
    return ""


# ============ 主调用函数 ============
async def call_dsh(prompt: str, from_id: str, task_type: str) -> dict:
    """
    调用 dsh 处理任务，返回 {"text": str, "model": str} 或抛出异常。
    失败时上层应该捕获并降级到 claude/mock。
    """
    # 1. cookies
    cookies, ch = _get_cookies()

    # 2. 拿 sessionId（复用 or 新建）
    sid = _get_session_id(from_id, task_type)
    if not sid:
        sid = _rpc("session/create", {"request": {}}, ch)["sessionId"]
        _rpc(
            "session/selectModel",
            {"request": {"sessionId": sid, "provider": PROVIDER, "model": MODEL}},
            ch,
        )
        _set_session_id(from_id, task_type, sid)

    # 3. 打开 follow WebSocket（独立连接，避免阻塞）
    follow_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())

    async with websockets.connect(
        WS_URL,
        additional_headers={"Cookie": ch},
        max_size=64 * 1024 * 1024,
    ) as ws:
        await ws.send(json.dumps({
            "type": "open",
            "streamId": follow_id,
            "endpoint": "session/follow",
            "payload": {"args": {"request": {
                "address": {"kind": "session", "sessionId": sid}
            }}},
        }))

        # 4. 发 prompt（HTTP 立即返回）
        _rpc(
            "session/prompt",
            {"request": {
                "requestId": request_id,
                "sessionId": sid,
                "mode": "queue",
                "content": [{"type": "text", "text": prompt}],
            }},
            ch,
        )

        # 5. 等 follow 流，提取最终回复
        deadline = time.time() + FOLLOW_TIMEOUT
        latest_text = ""
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=deadline - time.time()
                )
            except asyncio.TimeoutError:
                break
            data = json.loads(raw)
            if data.get("streamId") != follow_id:
                continue
            if data["type"] == "error":
                raise RuntimeError(f"follow 错误: {data.get('error')}")
            if data["type"] == "end":
                break
            if data["type"] == "item":
                text = _extract_assistant_text(data.get("value", {}))
                if text:
                    latest_text = text  # 取最新（流式场景下是累积最新）

        if not latest_text:
            raise RuntimeError("follow 流里没拿到 assistant 回复")

        return {"text": latest_text, "model": MODEL, "sessionId": sid}
