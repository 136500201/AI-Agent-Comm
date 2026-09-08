# A2A Mesh 文档（B 电脑视角）

> 你好 B 电脑运维！这是给你的文档入口。

---

## 🚨 如果你之前已经部署过，请先看更新指南

A 电脑修了 4 个关键 bug，B 端 daemon 需要更新才能正常通信。

📄 **更新指南**：[B-UPDATE.md](./B-UPDATE.md)

3 步：拉代码 → 杀旧 daemon → 启动新 daemon

---

## 🤖 如果你想让 B-Agent 真正"动脑子"（Phase 6）

升级 B daemon 用真 Claude API（替代 mock）。

📄 **Claude 升级指南**：[B-CLAUDE-UPGRADE.md](./B-CLAUDE-UPGRADE.md)

5 步：拉代码 → 装 anthropic → 配 API Key → 重启 daemon

---

## 📚 如果你是第一次部署

📄 **部署指南**：[B-DEPLOY.md](./B-DEPLOY.md)

15-20 分钟：从克隆代码到 daemon 上线。

---

## 📂 完整文档

| 文档 | 用途 |
|------|------|
| [B-DEPLOY.md](./B-DEPLOY.md) | 首次部署（从 0 到上线） |
| [B-UPDATE.md](./B-UPDATE.md) | 代码更新（拉新代码 + 重启 daemon） |
| [B-CLAUDE-UPGRADE.md](./B-CLAUDE-UPGRADE.md) | Phase 6：升级真 Claude API |
| [README.md](../README.md) | 项目总览（架构、协议、Roadmap） |

---

**项目仓库**：https://github.com/136500201/AI-Agent-Comm  
**最后更新**：2026-09-08