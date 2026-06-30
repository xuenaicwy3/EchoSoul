# 当前迭代计划

## 已完成

- [x] Function Calling — 10 个陪伴工具
- [x] Skills 系统 — 4 个 SKILL.md 技能包
- [x] MCP 集成 — langchain-mcp-adapters
- [x] Human-in-the-Loop 中断 — 前后端审批卡片+resume
- [x] Harness 三层架构 — Context/Harness/Model 分离
- [x] ReAct Agent 图 — 7 节点替代原 4 节点
- [x] emotion + memory 并行执行
- [x] 工具可观测性 — EventBus + Redis 日志
- [x] SSE 流式对话 — graph.stream() + Celery + Redis pub/sub
- [x] 语音流式 — 队列+句子级缓冲，LLM 边生成边送 TTS
- [x] 语音播放队列 — 不截断
- [x] 前端中断审批卡片 — InterruptCard 组件

## 下一迭代

- [ ] 启用 Skills 系统 (`ENABLE_SKILLS=True`)
- [ ] 启用 MCP 连接 (`ENABLE_MCP=True`)
- [ ] FC 角色切换联动前端渲染
- [ ] MCP 服务器实现（`mcp_servers/companion_memory.py` 等）
- [ ] 单元测试补充 — 目标覆盖率 >60%
- [ ] 语音管线接入 Agent 图（记忆+情绪）

## 远期规划

- [ ] 多 Agent 系统激活 — 工具 >30 或跨领域拆分
- [ ] 音乐/绘画/小说/知识 等领域 Agent
- [ ] Alembic 数据库迁移
- [ ] 真逐 Token 流式（astream_events）
- [ ] 生产环境安全检查（P0 债务清零）
