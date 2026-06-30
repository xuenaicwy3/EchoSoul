# 已知问题与债务

## P0 — 安全（生产上线前必修）

| # | 问题 | 影响 |
|---|------|------|
| 1 | `.env` API Key 泄露到 Git 历史 | 阿里云后台更换所有 Key |
| 2 | `SECRET_KEY` 使用默认值 | 更换随机 256-bit 字符串 |
| 3 | CORS `allow_origins=["*"]` | 限制前端域名白名单 |

## P1 — 架构债务

| # | 问题 | 状态 |
|---|------|------|
| 4 | 无 Alembic 数据库迁移 | 表结构变更靠 `_ensure_*()` 运行时检查，不可版本化 |
| 5 | 新旧代码并存 | `app/` 根目录仍有旧文件，已有 16 个桥接模块 |
| 6 | ChromaDB 和 PG 数据同步非事务 | sync_all_layers 可能不一致 |
| 7 | 旧 `app/agent.py` 未被新架构引用 | Celery 已迁移到 `app/harness/agent.py`，旧文件待清理 |
| 8 | Skills 的 handler 回调未实现 | 激活后工具调用返回兜底消息 |
| 9 | 语音管线无记忆+无 Agent 图 | 语音走轻量 LLM 直出，跳过情绪分析/ChromaDB/FC |

## P2 — 功能遗留

| # | 问题 | 备注 |
|---|------|------|
| 10 | Live2D 表情切换不完整 | joy 正常，sad/anger/surprise 管线贯通但视觉不可见 |
| 11 | 测试覆盖率偏低 | 22 个集成测试（22/22 pass），核心模块目标 60% |
| 12 | LLM 延迟偏高 | DashScope API 3-6s/次，本地部署模型可降至 <1s |
| 13 | VRM 手臂姿势手动校正 | 临时方案，后续调 VRoid Studio 姿态重新导出 |
| 14 | MCP 服务器未实现 | 配置就绪，`mcp_servers/` 包内待写 |
| 15 | SSE 节点级推送（非真逐 Token）| `graph.stream()` 节点完成后推全文，等 LangGraph `astream_events` + `interrupt()` 成熟后升级 |
| 16 | Redis pubsub 偶现超时 | SSE 流结束清理时偶发，已加 keepalive 缓解 |
| 17 | FC 角色切换不联动前端渲染 | `set_role_style` 执行后 Live2D/VRM 模型不自动切换，需手动选角色 |
