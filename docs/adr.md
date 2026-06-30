# EchoSoul 架构决策记录 (ADR)

> CLAUDE.md 保持静态，所有架构决策的完整版本记录于此。

---

## ADR-1: 为什么用 ChromaDB 而不是 PG vector

**背景**：PostgreSQL 15 有 pgvector 扩展，可以省去一个独立服务。

**决策**：使用 ChromaDB HTTP 模式。

**理由**：
- 三层记忆语义空间需向量距离计算（cosine），HNSW 索引比 pgvector IVFFlat 更快
- 独立服务嵌入缓存不污染 PG 连接池
- metadata 过滤语法（`$and`）天然适合 `user_id + role_type`

**代价**：多一个进程（Windows: `chroma run`）；PG-Chroma 同步非事务

---

## ADR-2: 为什么用 EventBus 而不是直接方法调用

**背景**：旧 `agent.finalize_conversation()` 串行 6 种副作用，耦合极重。

**决策**：进程内 EventBus（`core/events.py`），`chat.completed` 事件触发 9 个独立 handler。

**代价**：调试调用栈不如直接调用清晰

---

## ADR-3: 为什么 Celery + EventBus 混合架构

**背景**：~5s LLM 调用如果在 FastAPI 内执行，阻塞进程资源。

**决策**：Celery 管重活（LLM 调用）+ EventBus 管副作用（DB/WS），通过 Redis Stream 桥接。

**理由**：
- FastAPI 保持轻量：POST /chat <10ms 返回 task_id
- Celery Worker 独立扩缩：`--concurrency=4`→0.8 任务/秒
- 任务重试(2 次)、退避(5s)、超时(60s)、ack_late 防丢失

**代价**：多一个 Celery Worker 进程

---

## ADR-4: 为什么用 Repository 模式

**背景**：`select(UserFact).where(...)` 散落 5+ 个 Service。

**决策**：每表一个 Repository，继承 `BaseRepository[T]`。

**代价**：文件数量增加；简单查询也走间接调用

---

## ADR-5: 为什么 MemoryDecayEngine 用两阶段衰减模型

**决策**：Igarashi et al. (2022) 模型 — 指数衰减（前 10 天）→ 幂律衰减（10 天后）。

**代价**：公式比纯指数复杂

---

## ADR-6: 为什么 WebSocket 而不是 WebRTC 做语音对话

**背景**：语音对话需要低延迟音频传输，WebRTC 和 WebSocket 都可以。

**决策**：WebSocket 双向流，不用 WebRTC。

**理由**：
- WebRTC 用于浏览器间 P2P 视频通话，AI 伴侣是 C/S 音频传输
- Open-LLM-VTuber (11k+ Stars) / Xue Lin / AIRI 全部用 WebSocket
- 不需要 STUN/TURN 服务器，不需要信令交换

**代价**：没有 WebRTC 的抖动缓冲和拥塞控制（语音场景不需要）

---

## ADR-7: 为什么用 LLM 关键词注入做表情而不是后端映射

**背景**：EchoSoul 已有 EmotionService 输出 19 种情绪标签，可直接映射 Live2D 表情。

**决策**：借鉴 Open-LLM-VTuber，在 LLM 系统提示词注入表情标签指令。

**理由**：
- LLM 自然输出 `[joy]` `[blush]` 比后端映射更流畅
- 一句话内可以切换多种表情
- 不需要额外维护 emotion→expression 映射表
- 表情控制粒度是句子级而非消息级

**代价**：消耗少量 token；需要清洗表情标签后再送 TTS

---

## ADR-8: 采用 Harness 三层架构

**背景**: EchoSoul 需要频繁迭代（新增工具、调整角色人设、优化记忆策略），每次改动不应触及 Agent 核心图结构或重新训练模型。

**决策**: 采用字节跳动 DeerFlow 的 Harness 三层架构 — Context 层（高频变、改数据）、Harness 层（中频变、改配置）、Model 层（低频变、改 API）。

**理由**：
- 90% 的迭代（加工具、调人设、改衰减参数）只需改 Context 或 Harness 层
- 与 DeerFlow 核心设计理念完全一致
- 预留多 Agent 扩展接口（MultiAgentHarness）

**代价**：三层间有明确接口约束，违反会导致运行时错误

---

## ADR-9: Function Calling + Skills + MCP 三层工具体系

**背景**: Agent 需要调用外部工具（记忆检索、好感度更新、游戏操作等），但不同工具的来源和管理方式不同。

**决策**: 三来源统一 ToolRegistry：
- **Function Calling**: 10 个内置陪伴工具，随 Agent 启动常驻
- **Skills**: SKILL.md 技能包，按触发词动态激活/停用
- **MCP**: 外部 MCP 服务器工具，通过 langchain-mcp-adapters 接入

**理由**：
- LLM 通过 `bind_tools()` 看到统一的工具列表
- Skills 的渐进加载节省 token（不活跃技能不占用上下文）
- MCP 标准化外部工具接入，换提供商不改代码

**代价**：ToolRegistry 是单点，需保证线程安全

**参考**：Open-LLM-VTuber (3-tier tool calling)、Fay (LangGraph + MCP)、Anthropic Agent Skills 标准

---

## ADR-10: ReAct Agent + Human-in-the-Loop 中断

**背景**: 原 4 节点线性工作流（select_role → emotion → memory → generate）无法调用工具，也没有人工审批机制。

**决策**: 7 节点 ReAct StateGraph + `interrupt()` 中断：
- `router`: LLM + bind_tools 决策
- `interrupt_check`: 敏感工具（save_memory/update_affection 等 5 个写入操作）暂停等审批
- `tool_exec`: 执行通过审批的工具
- 安全工具（recall_memory/read_emotion 等 5 个只读操作）自动通过

**理由**：
- 防止 AI 擅自修改用户数据
- LangGraph `interrupt()` + `Command(resume=...)` 是官方标准 HITL 模式
- PostgresSaver 持久化中断状态，跨重启存活

**代价**：中断增加一轮用户交互延迟（~2-5s 等待审批）

---

## ADR-11: 单 Agent vs 多 Agent

**背景**: 字节 DeerFlow 使用 Manager-Worker 多 Agent 模式，是否需要跟进。

**决策**: 当前阶段使用单 Agent。满足以下条件时激活 MultiAgentHarness：
1. 工具数 > 30
2. 工具跨完全不相关领域（音乐/绘画/小说/游戏）
3. 每个领域需要独立上下文和决策逻辑

**理由**：
- 单 Agent 延迟更低（无 Agent 间通信开销）
- 人格一致性更好（一个大脑统一角色语气）
- 当前 10 个工具均在陪伴领域内，一个 Agent 完全管得过来
- 已预留 `MultiAgentHarness` 接口，升级不重写

**代价**：后续拆分需重新设计 Lead Agent 路由策略

**参考**：字节框架选型标准 — 10+ 工具 + 有状态流转 + 人工审批 → LangGraph（我们在这一层）

---

## ADR-12: SSE 流式对话 + 语音流式

**背景**: 文字对话 Celery 轮询模式 5-15s 无反馈，语音管线 LLM.invoke() 等全文返回才送 TTS。

**决策**:
- 文字通道：`llm.stream()` 替换 `llm.invoke()`，`graph.astream_events(version="v2")` 捕获 `on_chat_model_stream` 事件，FastAPI `StreamingResponse(text/event-stream)` 逐 token 推送
- 语音通道：线程池跑 sync stream → async Queue → 句子级缓冲（检测。！？）→ 整句送 CosyVoice TTS，LLM 边生成边播放

**理由**:
- 首 Token/首句 ~1-2s（vs 原来 5-15s），感知延迟大幅降低
- 语音句子级缓冲保证 TTS 拿到完整句子，不截断
- 两套端点并行（POST /chat Celery + POST /chat/stream SSE），兼容现有架构

**代价**: SSE 端点不走 Celery，直接占用 FastAPI worker；高并发需配合 worker 扩容
