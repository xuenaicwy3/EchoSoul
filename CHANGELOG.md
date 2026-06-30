# 项目变更与修复记录

## 已完成的重要修复

| # | 问题 | 解决方案 |
|---|------|---------|
| ✅ | React DOM 与 PIXI WebGL 冲突 | PIXI 自管 canvas，React 管 div 容器 |
| ✅ | pixi-live2d-display-lipsyncpatch 不兼容 Cubism 3.1 | 回退 pixi-live2d-display@0.4.0 原版 |
| ✅ | Cubism Core 加载时序 | index.html `<script>` 同步加载 CDN |
| ✅ | Celery 被错误移除导致阻塞 | ADR-3 修正，恢复 Celery + EventBus 混合 |
| ✅ | miku_pro 模型无法渲染 | 确认 pixi-live2d-display@0.4.0 兼容 Cubism5 |
| ✅ | CosyVoice V2 废弃 GET 错误 | 切换 cosyvoice-v3-flash + _v3 音色 |
| ✅ | TTS 音频不播放 | useAudioPlayer AudioContext 解码 WAV base64 |
| ✅ | 口型太小声 | Power Curve + Lerp 平滑 + 参数范围 x2 |

## 已完成的重大特性

| # | 特性 | 说明 |
|---|------|------|
| ✅ | Function Calling | 10 个陪伴工具，LLM 通过 bind_tools() 主动调用 |
| ✅ | Skills 系统 | 4 个 SKILL.md 技能包，三级渐进加载，按需激活 |
| ✅ | MCP 集成 | langchain-mcp-adapters + MultiServerMCPClient + 工具适配 |
| ✅ | Human-in-the-Loop 中断 | interrupt() + Command(resume)，5 个敏感工具写操作需审批 |
| ✅ | Harness 三层架构 | 字节 DeerFlow 同款 Context/Harness/Model 分离 |
| ✅ | 多 Agent 扩展接口 | MultiAgentHarness Manager-Worker 模式预留 |
| ✅ | ReAct Agent 图 | 7 节点（含 interrupt_check）替代原 4 节点线性工作流 |
| ✅ | 工具可观测性 | EventBus tool.called/skill.activated 事件 + Redis 日志缓冲区 |
| ✅ | SSE 流式对话 | graph.stream() + Celery + Redis pub/sub 流式推送 |
| ✅ | 语音流式 | 队列+句子级缓冲，LLM 边生成边送 TTS |
| ✅ | 中断审批前后端 | InterruptCard 组件 + resume 端点 + CeleryResume 任务 |
| ✅ | emotion+memory 并行 | Annotated + _keep_latest reducer，省 ~2s |
| ✅ | AsyncPostgresSaver | process_chat_resume 用 PG 持久化中断状态 |

## 修复记录

| # | 问题 | 解决方案 |
|---|------|---------|
| ✅ | router_node LLM invoke→stream | 逐 token 流式输出 |
| ✅ | 语音播放截断 | useAudioPlayer 加播放队列，onended 链式调度 |
| ✅ | 重复 ChromaDB 查询 | tasks.py/chat_stream.py 去掉 Context 层重复检索 |
| ✅ | 浏览器缓存旧 JS | middleware 加 Cache-Control: no-cache |
| ✅ | save_memory 字段错误 | UserFact 用 key/value 替代 content |
| ✅ | bcrypt 5.0 + passlib 不兼容 | auth.py 直接 bcrypt，去掉 passlib |
| ✅ | asyncio.run() 嵌套冲突 | process_chat_stream 切纯 sync，去掉 async 包裹 |

## 新增文件

| 文件 | 用途 |
|------|------|
| `app/harness/context.py` | Context 层 — 记忆/好感度/会话上下文 |
| `app/harness/model.py` | Model 层 — LLM 模型统一入口 |
| `app/harness/agent.py` | Harness 层 — 单 Agent 编排器 |
| `app/harness/multi_agent.py` | 多 Agent 扩展（预留） |
| `app/domain/agent/tools/` | Function Calling 工具基础设施 |
| `app/domain/agent/skills/` | Skills 技能系统 |
| `app/domain/agent/mcp/` | MCP 客户端 + 适配器 |
| `skills/*/SKILL.md` | 4 个技能定义文件 |
| `mcp_servers.json` | MCP 服务器配置 |
| `tests/integration/test_agent_tools_flow.py` | 集成测试 (22/22 passed) |
| `tests/TEST_REPORT.md` | 测试报告（面试速查） |
| `app/api/routers/chat_stream.py` | SSE 流式 + 中断恢复端点 |
| `frontend/src/components/chat/InterruptCard.tsx` | 中断审批卡片组件 |
| `docs/adr.md` | 架构决策记录（ADR-1~12） |
