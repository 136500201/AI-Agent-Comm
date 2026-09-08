# B 端 Claude API 升级指南

> **场景**：B daemon 从 mock 升级到真 Claude API（Phase 6）。升级后 B-Agent 能智能回复任务，不再是固定问答模板。
>
> **预计时间：5 分钟**

---

## 一、为什么升级

之前 B daemon 收到任务后返回的是固定 mock 答案（比如 requirement_clarification 永远返回那 3 个问题）。

升级后，B-Agent 由 Claude Sonnet 4.5 驱动，能根据任务内容智能生成回复，并保持多轮对话上下文。

**效果对比：**

| 场景 | 升级前 (mock) | 升级后 (Claude) |
|------|---------------|-----------------|
| A 提"用户积分系统"需求 | 固定 3 个问题 | 针对需求列出关键澄清点 + 初步架构建议 |
| A 发 code review | 模板回复 | 真实代码评审（bug/性能/可读性/安全） |
| 多轮对话 | 无上下文 | 自动保持会话历史（每 (sender, task_type) 20 轮） |

---

## 二、前置条件

1. ✅ 已按 [B-UPDATE.md](./B-UPDATE.md) 完成 Phase 5 bug 修复
2. ✅ 有 Anthropic API Key（去 https://console.anthropic.com 申请）
3. ✅ Python 3.9+

---

## 三、升级步骤

### Step 1：拉最新代码

```bash
cd ~/Documents/a2a-mesh   # 或你之前 clone 的路径
git pull origin main
```

应该看到新增/修改的文件：
```
 agent/claude_client.py   | 新增（约 110 行）
 agent/daemon.py          | 修改（接入 Claude）
 agent/requirements.txt   | 新增 anthropic 依赖
```

### Step 2：安装 anthropic 包

```bash
cd ~/Documents/a2a-mesh
pip3 install -r agent/requirements.txt
# 或单独装：
pip3 install 'anthropic>=0.40.0'
```

验证：
```bash
python3 -c "import anthropic; print(anthropic.__version__)"
# 应该输出 0.40.0 或更新版本
```

### Step 3：配置 API Key

编辑 `~/.a2a-mesh.env`（你的环境变量文件）：

```bash
nano ~/.a2a-mesh.env
```

加一行：
```bash
export ANTHROPIC_API_KEY="sk-ant-api03-xxxxxxxxxxxxxxxxxxxxx"
```

保存后让环境变量生效：
```bash
source ~/.a2a-mesh.env
echo "$ANTHROPIC_API_KEY" | head -c 20
# 应该看到 sk-ant-api03-xxxx 的开头
```

**⚠️ 安全提示**：
- 不要把 API Key 提交到 git
- 不要贴在聊天截图里
- 建议给 B-Agent 单独建一个 API Key（控制额度）

### Step 4：停掉旧 daemon

```bash
# 如果是 nohup 启动
kill $(cat ~/a2a-agent-B.pid)

# 如果是 LaunchAgent 启动（macOS）
launchctl unload ~/Library/LaunchAgents/com.a2amesh.agent.plist

# 确认停了
ps aux | grep daemon.py | grep -v grep
# 应该没输出
```

### Step 5：启动新 daemon

**前台测试**（先确认 Claude 接上了）：

```bash
cd ~/Documents/a2a-mesh
source ~/.a2a-mesh.env
python3 agent/daemon.py --id "$COMPUTER_ID" --token "$TOKEN" --hub "$HUB_URL"
```

**关键日志**（说明 Claude 已启用）：

```
[2026-xx-xx xx:xx:xx] ✅ Claude API 已启用 (model: claude-sonnet-4-5)
[2026-xx-xx xx:xx:xx] 连接 Hub: ws://8.156.83.217:8086/ws/computer-B?token=xxx
✅ computer-B 已上线
[computer-B]>
```

如果只看到 `连接 Hub` 但**没有** `✅ Claude API 已启用` 这一行，说明 `ANTHROPIC_API_KEY` 没读到，回去检查 Step 3。

按 `Ctrl+C` 退出前台测试。

**后台启动**：

```bash
# macOS LaunchAgent 方式
launchctl load ~/Library/LaunchAgents/com.a2amesh.agent.plist

# 或 nohup 方式
nohup python3 agent/daemon.py --id "$COMPUTER_ID" --token "$TOKEN" --hub "$HUB_URL" \
  < /dev/null > ~/a2a-agent-B.log 2>&1 &
echo $! > ~/a2a-agent-B.pid
```

---

## 四、验证 Claude 正常工作

让 A 发一个真实需求：

A 端执行（cli/ai_send.py）：
```bash
HUB_HTTP=http://8.156.83.217:8086 TOKEN=tok-A-dev-2026-a2a python3 cli/ai_send.py send \
  --from computer-A --to computer-B \
  --type requirement_clarification \
  --text "我想做一个文件同步工具，支持 macOS 和 Windows，定时把指定文件夹同步到云盘。请帮我列出还需要澄清的关键问题。"
```

**B 端 daemon 日志**会显示：
```
⚙️  处理任务: requirement_clarification from computer-A
📝 已回包: id=xxx
```

**A 端收到的 result.output.reply** 应该是 Claude 生成的智能回复（不是固定模板），类似：
> "针对文件同步工具这个需求，我建议先澄清以下关键问题：
> 1. 同步方向是单向（本地→云）还是双向？..."

如果看到智能回复，说明升级成功 ✅

也可以打开聊天页实时看：
```
http://8.156.83.217:8086/chat
```

---

## 五、Token 消耗参考

每次任务调用 Claude：
- 输入：约 200-1000 tokens（取决于任务复杂度 + 多轮历史）
- 输出：默认 max_tokens=2048

按 Sonnet 4.5 价格（约 \$3/MTok input, \$15/MTok output）：
- 一次简单 echo：~500 input + 100 output = $0.0017
- 一次 code review：~2000 input + 1500 output = $0.0285
- 多轮对话累积：每轮都带历史，最坏 20 轮后约 15k input

**建议**：
- API Key 设月度预算上限（比如 \$20）
- 不用时可以临时 unset：`unset ANTHROPIC_API_KEY`，daemon 会回退 mock

---

## 六、回滚（如果出问题）

### 临时回滚（不停 daemon）

```bash
# 在 daemon 进程里没法改环境变量，只能重启
# 先杀掉
kill $(cat ~/a2a-agent-B.pid)

# 临时禁用 Claude（mock 回退）
unset ANTHROPIC_API_KEY
nohup python3 agent/daemon.py --id "$COMPUTER_ID" --token "$TOKEN" --hub "$HUB_URL" \
  < /dev/null > ~/a2a-agent-B.log 2>&1 &
echo $! > ~/a2a-agent-B.pid
```

启动日志会显示：
```
⚠️ 无法 import claude_client，回退到 mock
```
或
```
[2026-xx-xx] 连接 Hub: ...
✅ computer-B 已上线    # 没有 Claude 启用行
```

### 代码回滚

```bash
cd ~/Documents/a2a-mesh
git log --oneline -5
git checkout <commit-before-claude> -- agent/
pip3 uninstall -y anthropic
# 重启 daemon
```

---

## 七、常见问题

**Q：API Key 没问题但 daemon 报 "authentication_error"？**
A：检查 Key 是不是 sk-ant-api03- 开头，不是 sk-ant-01- 的旧格式。

**Q：每次任务都报 "rate_limit_error"？**
A：账户 tier 不够。Console 里把账户升级到 Build Tier 1+。

**Q：升级后 daemon 起不来，提示 `ModuleNotFoundError: No module named 'anthropic'`？**
A：Step 2 没装或装到了别的 Python 环境。`which python3` 确认 daemon 用的是哪个 python，然后用对应的 pip：
```bash
python3 -m pip install anthropic
```

**Q：想强制用 mock 测一下对比效果？**
A：
```bash
kill $(cat ~/a2a-agent-B.pid)
unset ANTHROPIC_API_KEY
nohup python3 agent/daemon.py ... &   # 不带 API key，自动 mock
echo $! > ~/a2a-agent-B.pid
```

---

## 八、联系

升级过程中遇到问题，提供：
1. `git pull` 完整输出
2. `pip3 install anthropic` 完整输出
3. daemon 启动日志（`~/a2a-agent-B.log`）
4. （如果有）A 端发的任务原文 + B 端 result

---

**最后更新**：2026-09-08  
**对应 Phase**：Phase 6 - Claude API 接入  
**项目地址**：https://github.com/136500201/AI-Agent-Comm
