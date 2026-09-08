"""
A2A Mesh - Claude API 客户端
异步调用 Anthropic Claude API，支持多轮对话上下文。
"""
import os
import asyncio
import anthropic


SYSTEM_PROMPT = """你是 B 电脑上的 AI Agent，名字叫 "B-Agent"。
你的任务：接收来自 A 电脑的协作任务，根据任务类型智能处理后返回结果。
你正在协助开发/测试一个项目，请用专业、简洁、可操作的方式回应。
回答用中文，除非任务明确要求其他语言。
"""


# 简单内存会话存储：key = "{from}::{task_type}"，value = messages list
_sessions: dict = {}


def _get_session(from_id: str, task_type: str) -> list:
    key = f"{from_id}::{task_type}"
    return _sessions.setdefault(key, [])


def _build_task_prompt(task: dict) -> str:
    """把 task 转换成 Claude prompt"""
    task_type = task.get("type", "unknown")
    task_input = task.get("input", {})

    if task_type == "requirement_clarification":
        req = task_input.get("requirement") or task_input.get("text", "")
        ctx = task_input.get("context", "")
        prompt = f"需求澄清任务：\n\n需求：{req}\n\n背景：{ctx}\n\n请分析这个需求是否清晰，列出还需要澄清的关键问题（如果有），以及你的初步理解。"
    elif task_type == "code_review":
        code = task_input.get("code", "")
        diff = task_input.get("diff", "")
        prompt = f"代码评审任务：\n\n代码：\n```\n{code or diff}\n```\n\n请评审这段代码，指出：1)潜在 bug 2)性能问题 3)可读性 4)安全风险 5)改进建议。"
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
        # 通用：把整个 input 当文本处理
        prompt = f"任务类型：{task_type}\n\n输入：\n{json.dumps(task_input, ensure_ascii=False, indent=2)}"

    return prompt


async def call_claude(prompt: str, from_id: str, task_type: str, max_tokens: int = 2048) -> dict:
    """
    调用 Claude API 处理任务，支持多轮对话上下文。
    返回 {"text": str, "session_messages": list} 或错误。
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "error": "ANTHROPIC_API_KEY not set",
            "hint": "请设置环境变量 ANTHROPIC_API_KEY=sk-ant-..."
        }

    history = _get_session(from_id, task_type)

    try:
        # 同步 SDK 用 to_thread 包成异步
        def _sync_call():
            client = anthropic.Anthropic(api_key=api_key)
            messages = history + [{"role": "user", "content": prompt}]
            response = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=messages
            )
            return response, messages

        response, all_messages = await asyncio.to_thread(_sync_call)

        assistant_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                assistant_text += block.text

        # 更新 session
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": assistant_text})

        # 限制 history 长度（防止 token 超限）
        if len(history) > 20:
            _sessions[f"{from_id}::{task_type}"] = history[-20:]

        return {
            "text": assistant_text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            "model": response.model,
        }

    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


import json  # 放在最后避免循环