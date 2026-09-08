"""
A2A Mesh - CLI 工具
ai-send: 发送消息给其他电脑
ai-history: 查看历史消息
"""
import argparse
import json
import os
import requests

HUB_HTTP = os.getenv("HUB_HTTP", "http://127.0.0.1:8086")
TOKEN = os.getenv("TOKEN", "tok-A-dev-2026")

def cmd_send(args):
    """发送任务给指定电脑"""
    if args.input_file:
        with open(args.input_file) as f:
            task_input = json.load(f) if args.input_file.endswith(".json") else {"text": f.read()}
    elif args.text:
        task_input = {"text": args.text}
    else:
        task_input = {}

    payload = {
        "task": {
            "type": args.type,
            "input": task_input,
        }
    }
    resp = requests.post(
        f"{HUB_HTTP}/api/send",
        json={"frm": args.from_id, "too": args.to, "payload": payload},
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=10,
    )
    print(json.dumps(resp.json(), ensure_ascii=False, indent=2))

def cmd_history(args):
    """查看历史"""
    resp = requests.get(
        f"{HUB_HTTP}/api/history/{args.computer_id}",
        params={"limit": args.limit},
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=10,
    )
    print(json.dumps(resp.json(), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    # send
    p_send = sub.add_parser("send", help="发送任务")
    p_send.add_argument("--from", dest="from_id", required=True, help="发送方 computer ID")
    p_send.add_argument("--to", required=True, help="目标 computer ID")
    p_send.add_argument("--type", default="chat", help="任务类型")
    p_send.add_argument("--text", help="文本输入")
    p_send.add_argument("--input-file", help="从文件读取输入 (JSON or text)")
    p_send.set_defaults(func=cmd_send)

    # history
    p_hist = sub.add_parser("history", help="查看历史")
    p_hist.add_argument("computer_id", help="computer ID")
    p_hist.add_argument("--limit", type=int, default=20)
    p_hist.set_defaults(func=cmd_history)

    args = parser.parse_args()
    args.func(args)
