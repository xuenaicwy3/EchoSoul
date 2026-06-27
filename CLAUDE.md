# CLAUDE.md
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 配置说明
- `.claude/settings.local.json` — 本地权限配置（allow/deny 规则）
- `.claude/settings.json` — 项目级共享配置
- `CLAUDE.md`（全局，位于 `~\.claude\`）— 用户级行为指令
- `claude.md`（本文件）— 项目级 Claude Code 指引

---

# EchoSoul — 心流虚拟伴侣

> 基于 LangGraph + 三层情感记忆 + Live2D 二次元形象的 AI 虚拟伴侣对话系统
>
> 最后更新：2026-06-26 | 维护者：endme

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈](#2-技术栈)
3. [架构总览](#3-架构总览)
4. [数据流](#4-数据流)
5. [模块地图与职责边界](#5-模块地图与职责边界)
6. [架构决策记录](#6-架构决策记录)
7. [数据库设计](#7-数据库设计)
8. [API 端点](#8-api-端点)
9. [配置项手册](#9-配置项手册)
10. [性能特征](#10-性能特征)
11. [测试策略](#11-测试策略)
12. [本地运行](#12-本地运行)
13. [开发约定](#13-开发约定)
14. [已知问题与债务](#14-已知问题与债务)

---

## 1. 项目概述

EchoSoul 是一个 AI 虚拟伴侣对话系统。核心能力：

- **多角色对话**：8 个预设角色（日系动漫/高冷御姐/傲娇辣妹/甜美校花/软萌可爱/温柔贤淑/元气少女/清冷仙气），每个角色独立人设、说话风格、开场白
- **Live2D 二次元形象**：每个角色配 Live2D 模型，支持表情驱动、口型同步、视线追踪、动作触发
- **实时语音对话**：用户可直接与 AI 角色语音聊天，低延迟 (<2s)，支持语音打断、双向自然对话
- **三层情感记忆**：事实层（用户个人信息）+ 情感层（情绪记录）+ 关系层（里程碑），基于艾宾浩斯遗忘曲线自动衰减
- **好感度养成**：四维（亲密度/信任度/趣味度/成长度），对话中自动增减，长时间不互动衰减
- **游戏化系统**：每日任务 / 成就 / 皮肤解锁
- **主动消息**：用户离线超时后 AI 自动生成问候
- **共创叙事**：多分支故事共同创作

---

## 2. 技术栈

### 2.1 后端运行时

| 技术 | 版本 | 角色 |
|------|------|------|
| Python | 3.11+ | 语言 |
| FastAPI | 0.115.x | HTTP + WebSocket 框架 |
| Uvicorn | 0.37.x | ASGI 服务器 |
| LangGraph | 1.2.x | 对话状态图编排（4 节点 DAG） |
| LangChain | 1.3.x | LLM 统一调用抽象 |
| langchain-openai | 1.2.x | OpenAI 兼容协议适配 |
| Pydantic v2 | 2.10.x | 请求/响应校验 + Settings 管理 |
| pydantic-settings | 2.14.x | .env 自动加载 |
| SQLAlchemy | 2.0.x | 异步 ORM |
| asyncpg | — | PostgreSQL 异步驱动 |
| psycopg | — | PostgreSQL 同步驱动（LangGraph checkpointer） |
| redis | 8.0.x | 缓存 + Stream 消息队列 |
| chromadb | 1.5.x | 向量存储（HTTP 客户端模式） |
| APScheduler | 3.11.x | 定时任务调度 |
| Celery | 5.6.x | 异步任务队列（LLM 调用） |
| python-jose | 3.3.x | JWT 签发/验证 |
| passlib[bcrypt] | 1.7.x | 密码哈希 |
| dashscope | 1.25.x | 阿里百炼 SDK（embedding） |
| langchain-community | 0.4.x | DashScope embeddings 集成 |

### 2.2 前端运行时

| 技术 | 版本 | 角色 |
|------|------|------|
| React | 19.x | UI 框架 |
| TypeScript | 5.x | 类型安全 |
| Vite | 6.x | 构建工具 |
| TailwindCSS | 4.x | 原子化样式 |
| Zustand | 5.x | 轻量状态管理 |
| React Router | 7.x | SPA 路由 |
| pixi.js | 8.x | WebGL 渲染引擎 |
| @pixi/live2d-display-cubism4 | — | Live2D Cubism 4 模型渲染 |
| @ricky0123/vad-web | — | 浏览器端语音活动检测 (VAD) |
| Web Audio API | — | 音频采集/播放 |
| MediaRecorder API | — | 麦克风录音 |

### 2.3 外部服务

| 服务 | 版本 | 端口 | 用途 |
|------|------|------|------|
| PostgreSQL | 15+ | 5432 | 主数据库 |
| Redis | 7+ | 6379 | 缓存/队列 |
| ChromaDB | 1.5.x | 8000 | 向量存储（HTTP 模式） |
| 阿里百炼 API | — | HTTPS | LLM 对话/情绪分析/Embedding |

### 2.4 AI 模型

| 模型 | 提供商 | 用途 | 调用方式 |
|------|--------|------|---------|
| DeepSeek-V4-Pro | 阿里百炼 | 主对话生成 | langchain-openai (兼容协议) |
| Qwen3.7-Plus | 阿里百炼 | 结构化情绪分析 | langchain-openai + function_calling |
| text-embedding-v4 | 阿里百炼 | 文本向量化 (1536d) | DashScope SDK |
| FunASR SenseVoiceSmall | — | 语音识别 (ASR) | 本地离线 |
| GPT-SoVITS / 阿里云 TTS | — | 语音合成 (TTS) | API + 本地 |

---

## 3. 架构总览

### 3.1 分层架构

```
┌──────────────────────────────────────────────────────────┐
│                   frontend/  (React SPA)                  │
│  LoginPage  ChatPage  GamePage  StoryPage  MemoryPage    │
│  Live2DCanvas  VoiceControl  ChatPanel  RoleSelector     │
│                                                          │
│  ┌─────────文字通道──────────┐  ┌────语音通道───────────┐ │
│  │ HTTP POST /chat           │  │ WebSocket 双向流      │ │
│  │ → task_id → 轮询结果       │  │ mic-audio → ASR→LLM→  │ │
│  └───────────────────────────┘  │ TTS→audio-chunk→前端  │ │
│                                 └───────────────────────┘ │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP + WebSocket
┌────────────────────────▼─────────────────────────────────┐
│                     api/  (表示层)                        │
│  routers/chat.py  voice.py  game.py  story.py  memory.py │
│  middleware.py        error_handlers.py        deps.py    │
└────────────────────────┬────────────────────────────────┘
                         │ Depends → 调用 domain service
┌────────────────────────▼────────────────────────────────┐
│                   domain/  (领域层)                       │
│  agent/  │ memory/  │ emotion/  │ affection/  │ game/    │
│  story/  │ tts/     │ voice/    │ roles/                │
│                                                          │
│  业务规则 | 状态机 | 算法 | 提示词                         │
│  发射事件 → core/events.py                                │
└──────┬──────────────────────────────┬────────────────────┘
       │ Repository 注入               │ LLM / Chroma 调用
┌──────▼──────────────────────┐  ┌────▼──────────────────┐
│  infrastructure/ (基础设施)   │  │  core/ (工具层)        │
│  database.py  redis.py       │  │  config.py             │
│  chroma.py    llm.py         │  │  exceptions.py         │
│  repositories/               │  │  events.py             │
│    base.py  *_repo.py        │  │  logging_config.py     │
└──────────┬───────────────────┘  └───────────────────────┘
           │
┌──────────▼───────────────────────────────────────────────┐
│                 models/  (数据模型)                        │
│    db_models.py    │    schemas.py    │    user.py        │
└──────────────────────────────────────────────────────────┘
```

### 3.2 依赖方向

```
api → domain → infrastructure → models
api → domain → core/events
domain → infrastructure/llm
domain → infrastructure/chroma
core → (无依赖)
```

**硬约束**：api 层禁止直接访问 database/redis/chroma。domain 层禁止导入 api 层任何符号。禁止循环导入。

### 3.3 完整目录树

```
EchoSoul/
├── .env.example
├── .gitignore
├── CLAUDE.md                       # ← 本文件
├── pyproject.toml                  # ruff / mypy / pytest
├── requirements.txt
├── requirements-dev.txt
├── Makefile
├── run.py
│
├── frontend/                       # React SPA（新建）
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── public/
│   │   └── live2d/                 # Live2D 模型文件
│   │       ├── haru/               #   日系动漫型
│   │       ├── hiyori/             #   高冷御姐型
│   │       └── ...                 #   每角色一个目录
│   └── src/
│       ├── main.tsx                # React 入口
│       ├── App.tsx                 # Router 根组件
│       ├── api/
│       │   └── client.ts           # axios + JWT interceptor
│       ├── hooks/
│       │   ├── useWebSocket.ts     # WS 连接/心跳/重连
│       │   ├── useChat.ts          # 文字聊天逻辑
│       │   ├── useVoiceChat.ts     # 语音对话主逻辑
│       │   ├── useVAD.ts           # 浏览器端 VAD
│       │   ├── useAudioPlayer.ts   # 音频播放 + 口型同步
│       │   └── useLive2D.ts        # Live2D 模型控制
│       ├── store/
│       │   ├── authStore.ts        # JWT token + 用户信息
│       │   ├── chatStore.ts        # 消息列表 + 对话状态
│       │   └── roleStore.ts        # 当前角色 + Live2D 模型
│       ├── components/
│       │   ├── live2d/
│       │   │   ├── Live2DCanvas.tsx     # PixiJS WebGL 画布
│       │   │   ├── Live2DModel.tsx      # 模型加载/卸载
│       │   │   └── ExpressionController.tsx
│       │   ├── chat/
│       │   │   ├── ChatWindow.tsx       # 消息列表
│       │   │   ├── MessageBubble.tsx    # 消息气泡
│       │   │   └── ChatInput.tsx        # 输入框
│       │   ├── voice/
│       │   │   ├── VoiceControl.tsx     # 🎤 按钮 + 音量指示
│       │   │   └── ASRPreview.tsx       # 实时识别预览
│       │   ├── role/
│       │   │   ├── RoleSelector.tsx     # 角色切换面板
│       │   │   └── RoleCard.tsx         # 角色卡片
│       │   ├── game/
│       │   │   ├── DailyTasks.tsx
│       │   │   ├── Achievements.tsx
│       │   │   └── SkinPanel.tsx
│       │   └── common/
│       │       ├── Header.tsx
│       │       └── ProtectedRoute.tsx
│       ├── pages/
│       │   ├── LoginPage.tsx
│       │   ├── RegisterPage.tsx
│       │   ├── HomePage.tsx            # 角色选择
│       │   ├── ChatPage.tsx            # 核心: Live2D + 聊天
│       │   ├── GamePage.tsx
│       │   ├── StoryPage.tsx
│       │   └── MemoryPage.tsx
│       └── types/
│           ├── chat.ts
│           ├── role.ts
│           ├── voice.ts
│           └── live2d.ts
│
├── app/                            # Python 后端
│   ├── __init__.py
│   ├── main.py                     # create_app() (~120行)
│   ├── celery_app.py               # Celery 实例 + 生产级配置
│   ├── tasks.py                    # @shared_task 定义
│   ├── task_registry.py            # 类型安全的 Celery 任务调用层
│   │
│   ├── api/                        # 表示层
│   │   ├── __init__.py
│   │   ├── deps.py                 # Depends 集中定义
│   │   ├── middleware.py            # CORS / Request-ID / 慢请求告警
│   │   ├── error_handlers.py       # 全局异常 → JSON
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── auth.py             # POST /auth/register  /auth/login
│   │       ├── chat.py             # POST /chat  GET /affection/{role}  /chat_history/{role}
│   │       ├── voice.py            # WS /ws/voice/{user_id} 语音对话端点
│   │       ├── game.py             # GET/POST /game/*
│   │       ├── story.py            # GET/POST /story/*
│   │       ├── memory.py           # GET /memory/* 情感记忆查询
│   │       └── ws.py               # WS /ws/{user_id}?token= 推送端点
│   │
│   ├── core/                       # 纯工具层
│   │   ├── __init__.py
│   │   ├── config.py               # Settings + get_settings() @lru_cache
│   │   ├── exceptions.py           # EchoSoulException → 15 子类
│   │   ├── events.py               # EventBus 进程内 pub/sub
│   │   └── logging_config.py       # setup_logging()
│   │
│   ├── domain/                     # 领域层
│   │   ├── __init__.py
│   │   ├── agent/                  # 对话智能体
│   │   │   ├── __init__.py
│   │   │   ├── graph.py            # EchoSoulAgent + _build_graph()
│   │   │   ├── nodes.py            # 4节点 + expression 标签
│   │   │   └── prompts.py          # PromptFactory
│   │   ├── memory/                 # 三层情感记忆
│   │   │   ├── __init__.py
│   │   │   ├── decay_engine.py     # MemoryDecayEngine
│   │   │   ├── affective_service.py# AffectiveMemoryService
│   │   │   ├── vector_service.py   # VectorMemoryService
│   │   │   └── retrieval_router.py # MemoryRetrievalRouter
│   │   ├── voice/                  # 语音对话（新增）
│   │   │   ├── __init__.py
│   │   │   ├── asr_service.py      # ASR 封装 (FunASR/Faster-Whisper)
│   │   │   ├── tts_service.py      # TTS 封装 (GPT-SoVITS/阿里云流式)
│   │   │   └── voice_pipeline.py   # ASR→LLM→TTS 流式管线
│   │   ├── emotion/                # 情绪分析
│   │   │   └── service.py          # EmotionService
│   │   ├── affection/              # 好感度系统
│   │   │   └── service.py          # AffectionService
│   │   ├── game/                   # 游戏化养成
│   │   │   └── service.py          # GameService
│   │   ├── story/                  # 共创叙事
│   │   │   └── service.py          # StoryService
│   │   ├── tts/                    # TTS 服务（已有）
│   │   │   └── service.py          # TTSService
│   │   └── roles/                  # 角色管理
│   │       └── catalog.py          # Role dataclass + live2d_model_path
│   │
│   ├── infrastructure/             # 基础设施层
│   │   ├── __init__.py
│   │   ├── database.py             # AsyncEngine + sessionmaker
│   │   ├── redis.py                # 异步 Redis 客户端
│   │   ├── chroma.py               # ChromaDB HttpClient
│   │   ├── llm.py                  # 统一 LLM 工厂
│   │   └── repositories/
│   │       ├── __init__.py
│   │       ├── base.py             # BaseRepository[T]
│   │       ├── user_repo.py        # UserRepository
│   │       ├── chat_history_repo.py# ChatHistoryRepository
│   │       ├── affection_repo.py   # AffectionRepository
│   │       ├── fact_repo.py        # FactRepository
│   │       ├── emotion_record_repo.py
│   │       ├── milestone_repo.py   # MilestoneRepository
│   │       └── memory_summary_repo.py
│   │
│   ├── models/                     # 数据模型
│   │   ├── __init__.py
│   │   ├── db_models.py            # 16 张表 ORM
│   │   ├── schemas.py              # Pydantic 模型
│   │   └── user.py                 # User ORM
│   │
│   └── workers/                    # 后台 Worker
│       ├── __init__.py
│       ├── postprocess.py          # Redis Stream Consumer + EventBus handlers
│       └── scheduler.py            # ProactiveScheduler
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_decay_engine.py
│   │   ├── test_event_bus.py
│   │   └── test_retrieval_router.py
│   └── integration/
│       ├── __init__.py
│       └── test_chat_api.py
│
└── scripts/
    ├── init_db.py
    └── seed_data.py
```

---

## 4. 数据流

### 4.1 文字通道（Celery + EventBus 混合，已有）

```
Client                    FastAPI                    Celery Worker
  │                         │                           │
  │ POST /chat              │                           │
  │────────────────────────▶│                           │
  │                         │ send_chat_task()          │
  │                         │──────────────────────────▶│
  │    {"task_id": "xxx"}   │                           │
  │◀────────────────────────│                           │
  │                         │                           │
  │ GET /chat/result/{id}   │                   ┌───────┴──────────┐
  │────────────────────────▶│                   │ agent.invoke()    │
  │◀────────────────────────│                   │ ~5s LLM          │
  │                         │                   │ 结果 → Redis      │
  │                         │  Stream Consumer   │ 数据 → Stream    │
  │                         │  → bus.emit()      └──────────────────┘
  │◀── WS push ─────────────│  → 9 handlers 并发
  │    (chat_reply)         │
```

### 4.2 语音通道（WebSocket 双向流，新增）

```
┌─ React 前端 ──────────────────────────────────────────────┐
│                                                           │
│  用户说话 → VAD 检测 → MediaRecorder 采集                   │
│  → WS push {"type":"mic-audio-data","data":"base64..."}    │
│                                                           │
│  接收 AI 语音:                                              │
│  ← WS receive {"type":"audio-chunk",                      │
│      "audio":"base64...",                                 │
│      "volumes":[0.1,0.3,...],   ← 口型同步                 │
│      "expressions":[1,2,1],      ← 表情切换                │
│      "text":"字幕文本"}                                    │
│  → AudioContext 播放 + Live2D 口型 + 表情切换               │
│                                                           │
└──────────────────────┬────────────────────────────────────┘
                       │ WebSocket /ws/voice/{user_id}
┌──────────────────────▼────────────────────────────────────┐
│  FastAPI 语音管线 (asyncio, 不走 Celery)                    │
│                                                           │
│  mic-audio-chunk 到达                                       │
│  → ASR (FunASR) → "我今天心情很好"                          │
│  → LLM 流式 (DeepSeek) → "哈哈 [joy] 真开心！..."          │
│  → TTS 流式 (GPT-SoVITS) → base64 + volumes + expressions  │
│  → audio-chunk 回传前端                                    │
│                                                           │
│  interrupt 消息到达 → 停止 LLM + 停止 TTS + 清空队列        │
└──────────────────────────────────────────────────────────┘
```

### 4.3 WebSocket 语音消息协议（借鉴 Open-LLM-VTuber）

```
Client → Server:
  {"type":"mic-audio-start"}                   # 用户开始说话
  {"type":"mic-audio-data","data":"base64..."} # 音频块 (流式)
  {"type":"mic-audio-end"}                    # 用户停止说话
  {"type":"interrupt"}                         # 打断 AI 说话

Server → Client:
  {"type":"asr-result","text":"识别的文本"}     # 实时 ASR 结果
  {"type":"asr-final","text":"最终文本"}        # ASR 最终结果
  {"type":"llm-stream","text":"流式文本"}       # LLM 流式输出
  {"type":"audio-chunk",                       # TTS 音频块
   "audio":"base64...",
   "volumes":[0.1,0.3,...],
   "slice_length_ms":20,
   "text":"当前句子字幕",
   "expressions":[1,2,1]}
  {"type":"speech-end"}                       # AI 说完
  {"type":"milestone","content":"..."}         # 里程碑推送
```

### 4.4 表情控制流程（借鉴 Open-LLM-VTuber LLM 关键词注入）

```
System Prompt 追加: "回复时可使用表情: [joy] [sad] [surprise] [anger] [neutral] [blush]"

LLM 输出: "哈哈 [joy] 今天真开心！你也是吗？[smile]"

后端处理:
  extract_expression_tags("哈哈 [joy] 今天真开心！你也是吗？[smile]")
  → expressions: [0, 5]      (joy→0, smile→5)
  → clean_text: "哈哈 今天真开心！你也是吗？"
  → TTS 合成(clean_text) + expressions → audio-chunk

前端处理:
  播放 audio → 按时间线切换 expressions[0] → expressions[5]
  Live2D 模型: ParamJoy=1.0 → ParamSmile=1.0
```

### 4.5 口型同步流程（借鉴 volumes 数组）

```
TTS 合成时:
  audio = synthesize(text, output_format="wav")
  volumes = [rms(audio[i:i+640]) for i in range(0, len(audio), 640)]
  # 每 20ms (16kHz×20ms=320 samples) 计算 RMS 音量

WebSocket 推送:
  {"type":"audio-chunk", "audio":"base64...", "volumes":[0.1,0.3,...], "slice_length_ms":20}

前端播放:
  audioSource.start()
  requestAnimationFrame(() => {
    currentTime = audioContext.currentTime - startTime
    volumeIndex = Math.floor(currentTime / 0.02)    # 20ms = 0.02s
    live2DModel.setParam("ParamMouthOpenY", volumes[volumeIndex])
  })
```

---

## 5. 模块地图与职责边界

### 5.1 domain/agent/ — 对话智能体

| 文件 | 管什么 | 不管什么 |
|------|--------|---------|
| `graph.py` | LangGraph StateGraph 构建 + invoke/ainvoke 入口 | 不管 LLM 实例创建；不管节点内部逻辑 |
| `nodes.py` | 四节点 + expression 标签注入 | 不管记忆存储（那是 postprocess handler） |
| `prompts.py` | 所有 LLM 提示词模板（含表情标签指令） | 不管表情提取逻辑 |

### 5.2 domain/voice/ — 语音对话（新增）

| 文件 | 管什么 | 不管什么 |
|------|--------|---------|
| `asr_service.py` | 语音识别：音频流 → 文本 | 不管 LLM 调用；不管 TTS |
| `tts_service.py` | 语音合成：文本 → 音频+volumes | 不管 ASR；不管 LLM 调用 |
| `voice_pipeline.py` | ASR→LLM→TTS 流式管线编排 | 不管 WebSocket 连接管理（那是 router 的职责） |

### 5.3 domain/roles/ — 角色管理

| 文件 | 管什么 | 不管什么 |
|------|--------|---------|
| `catalog.py` | Role dataclass + live2d_model_path | 不管模型文件加载（那是前端职责） |

### 5.4 api/routers/voice.py — 语音 WebSocket 端点（新增）

| 管什么 | 不管什么 |
|--------|---------|
| WebSocket 连接管理 / token 验证 / 消息路由到 voice_pipeline | 不管 ASR/LLM/TTS 具体实现 |

### 5.5 前端组件

| 组件 | 管什么 | 不管什么 |
|------|--------|---------|
| `Live2DCanvas` | PixiJS 初始化 + WebGL 渲染 + 模型生命周期 | 不管模型切换逻辑、表情映射 |
| `VoiceControl` | 🎤 按钮状态 / 音量指示 / VAD 启停 | 不管 WebSocket 发送、音频采集 |
| `ChatInput` | 文字输入框 + 发送按钮 + 语音模式切换 | 不管消息发送后的处理 |
| `useVoiceChat` | 语音对话主逻辑：采集→发送→接收→播放 | 不管 UI 渲染、不管文字通道 |
| `useVAD` | @ricky0123/vad-web 封装 + 静音检测 | 不管音频发送/接收 |
| `useAudioPlayer` | 音频播放 + volumes 口型同步 + expression 表情切换 | 不管 WebSocket 连接 |

---

## 6. 架构决策记录

### ADR-1: 为什么用 ChromaDB 而不是 PG vector？

**背景**：PostgreSQL 15 有 pgvector 扩展，可以省去一个独立服务。

**决策**：使用 ChromaDB HTTP 模式。

**理由**：
- 三层记忆语义空间需向量距离计算（cosine），HNSW 索引比 pgvector IVFFlat 更快
- 独立服务嵌入缓存不污染 PG 连接池
- metadata 过滤语法（`$and`）天然适合 `user_id + role_type`

**代价**：多一个进程（Windows: `chroma run`）；PG-Chroma 同步非事务

### ADR-2: 为什么用 EventBus 而不是直接方法调用？

**背景**：旧 `agent.finalize_conversation()` 串行 6 种副作用，耦合极重。

**决策**：进程内 EventBus（`core/events.py`），`chat.completed` 事件触发 9 个独立 handler。

**代价**：调试调用栈不如直接调用清晰

### ADR-3: 为什么 Celery + EventBus 混合架构？

**背景**：~5s LLM 调用如果在 FastAPI 内执行，阻塞进程资源。

**决策**：Celery 管重活（LLM 调用）+ EventBus 管副作用（DB/WS），通过 Redis Stream 桥接。

**理由**：
- FastAPI 保持轻量：POST /chat <10ms 返回 task_id
- Celery Worker 独立扩缩：`--concurrency=4`→0.8任务/秒
- 任务重试(2次)、退避(5s)、超时(60s)、ack_late 防丢失

**代价**：多一个 Celery Worker 进程

### ADR-4: 为什么用 Repository 模式？

**背景**：`select(UserFact).where(...)` 散落 5+ 个 Service。

**决策**：每表一个 Repository，继承 `BaseRepository[T]`。

**代价**：文件数量增加；简单查询也走间接调用

### ADR-5: 为什么 MemoryDecayEngine 用两阶段衰减模型？

**决策**：Igarashi et al. (2022) 模型 — 指数衰减（前 10 天）→ 幂律衰减（10 天后）。

**代价**：公式比纯指数复杂

### ADR-6: 为什么 WebSocket 而不是 WebRTC 做语音对话？

**背景**：语音对话需要低延迟音频传输，WebRTC 和 WebSocket 都可以。

**决策**：WebSocket 双向流，不用 WebRTC。

**理由**：
- WebRTC 用于浏览器间 P2P 视频通话，AI 伴侣是 C/S 音频传输
- Open-LLM-VTuber (3k+ Stars) / Xue Lin / AIRI 全部用 WebSocket
- WebSocket 协议简单，音频 base64 + volumes + expressions 一条消息承载所有数据
- 不需要 STUN/TURN 服务器，不需要信令交换

**代价**：没有 WebRTC 的抖动缓冲和拥塞控制（语音场景不需要）

### ADR-7: 为什么用 LLM 关键词注入做表情而不是后端映射？

**背景**：EchoSoul 已有 EmotionService 输出 19 种情绪标签，可直接映射 Live2D 表情。

**决策**：借鉴 Open-LLM-VTuber，在 LLM 系统提示词注入表情标签指令。

**理由**：
- LLM 自然输出 `[joy]` `[blush]` 比后端映射更流畅、更自然
- 一句话内可以切换多种表情（"哈哈[joy]真的吗？[surprise]"）
- 不需要额外维护 emotion→expression 映射表
- 表情控制粒度是句子级而非消息级

**代价**：消耗少量 token；需要清洗表情标签后再送 TTS

---

## 7. 数据库设计

（保持不变）

## 8. API 端点

### 8.1 认证（不需要登录）

| 方法 | 路径 | 请求体 | 响应 |
|------|------|--------|------|
| POST | `/auth/register` | `{username, password}` | `{access_token, user_id, token_type}` |
| POST | `/auth/login` | `{username, password}` | `{access_token, user_id, token_type}` |

### 8.2 文字聊天（需要 Bearer Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | `{message, role_type?}` → `{task_id}` |
| GET | `/chat/result/{task_id}` | 轮询结果 |
| GET | `/affection/{role_type}` | 好感度查询 |
| GET | `/chat_history/{role_type}?before=` | 分页历史 |
| DELETE | `/chat_history/{role_type}` | 删除历史 |
| GET | `/active_messages` | 主动消息 |

### 8.3 语音对话（新增）

| 方法 | 路径 | 说明 |
|------|------|------|
| WS | `/ws/voice/{user_id}?token=xxx` | 语音对话双向流 |

**WebSocket 消息类型**（见 4.3）

### 8.4 WebSocket 推送

| 路径 | 说明 |
|------|------|
| `WS /ws/{user_id}?token=xxx` | 文本/表情/里程碑推送 |

### 8.5 其余端点

（游戏化、情感记忆、页面路由 — 保持不变）

---

## 9. 配置项手册

（原有配置项保持不变，新增以下）

### 9.8 语音

| 配置项 | 默认值 | 影响 |
|--------|--------|------|
| `ASR_MODEL` | `funasr_sensevoice` | 语音识别模型 — 换模型影响准确度 |
| `TTS_MODEL` | `gpt_sovits` | 语音合成模型 — 影响自然度 |
| `TTS_VOICE_SPEED` | `1.0` | 语速 — 影响对话节奏 |
| `VAD_THRESHOLD` | `0.5` | 语音检测灵敏度 — 越高端越难触发 |
| `VAD_SILENCE_MS` | `500` | 静音判定时间 — 越大等待越久 |

### 9.9 前端

| 配置项 | 默认值 | 影响 |
|--------|--------|------|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | 后端 API 地址 |
| `VITE_WS_URL` | `ws://127.0.0.1:8000` | WebSocket 地址 |

---

## 10. 性能特征

### 10.1 文字通道耗时拆解

| 阶段 | 进程 | 操作 | 典型耗时 |
|------|------|------|---------|
| 1 | FastAPI | POST /chat → delay() → 返回 task_id | **<10ms** |
| 2 | Celery | Redis 缓存读取 | <5ms |
| 3 | Celery | ChromaDB 嵌入计算 | ~300ms |
| 4 | Celery | 情绪分析 (Qwen3.7) | ~1200ms |
| 5 | Celery | 回复生成 (DeepSeek) | ~3500ms |
| 6 | Celery | 结果写入 Redis | <5ms |
| 7 | FastAPI | Stream Consumer → EventBus 并发 | ~200ms |
| **Celery 总耗时** | | **~5.0s** | |

### 10.2 语音通道延迟目标

| 阶段 | 操作 | 目标延迟 |
|------|------|---------|
| 1 | VAD 语音结束检测 | <200ms |
| 2 | ASR (FunASR SenseVoice) | <500ms |
| 3 | LLM 首 Token (流式) | <1000ms |
| 4 | TTS 首句合成 | <500ms |
| **总延迟(说完→开始听到)** | | **<2.2s** |

### 10.3 扩容方案

| 场景 | 方案 |
|------|------|
| Celery 任务积压 | `celery worker --concurrency=8` |
| 语音并发高 | 增加 FastAPI workers: `uvicorn --workers=2` |
| LLM API 限流 | 调整 Celery `rate_limit` |
| ASR 瓶颈 | 单独部署 ASR 服务 |

---

## 12. 本地运行

### 前置条件

```bash
# 确保以下服务运行:
# PostgreSQL 15+ (端口 5432)
# Redis 7+ (端口 6379)
# ChromaDB HTTP (端口 8000): chroma run --path ./chroma_data
```

### 后端启动

```bash
cp .env.example .env  # 填入 DASHSCOPE_API_KEY
pip install -r requirements.txt

# 终端 1: Celery Worker
celery -A app.celery_app worker -P threads -c 4 --loglevel=info

# 终端 2: FastAPI
python run.py  # → http://127.0.0.1:8000
```

### 前端启动

```bash
cd frontend
npm install
npm run dev        # 开发: http://localhost:5173 (Vite HMR)

# 生产构建:
npm run build      # 输出 → app/static/
# 然后访问 http://127.0.0.1:8000  (FastAPI 托管)
```

---

## 13. 开发约定

（保持不变）

## 14. 已知问题与债务

### P0 — 安全（生产上线前必修）

| # | 问题 | 影响 |
|---|------|------|
| 1 | `.env` API Key 泄露到 Git 历史 | 阿里云后台更换所有 Key |
| 2 | `SECRET_KEY` 使用默认值 | 更换随机 256-bit 字符串 |
| 3 | CORS `allow_origins=["*"]` | 限制前端域名白名单 |

### P1 — 架构债务（下个迭代）

| # | 问题 | 状态 |
|---|------|------|
| 4 | 无 Alembic 数据库迁移 | 表结构变更靠 `_ensure_*()` 运行时检查，不可版本化 |
| 5 | 新旧代码并存 | `app/` 根目录仍有旧文件，已有 16 个桥接模块 |
| 6 | ChromaDB 和 PG 数据同步非事务 | sync_all_layers 可能不一致 |

### P2 — 功能遗留（3 项，CLAUDE.md 最后更新记录）

| # | 问题 | 备注 |
|---|------|------|
| 7 | **Live2D 表情切换不完整** | joy 正常，sad/anger/surprise 管线贯通但视觉不可见。hiYori Free 模型参数范围有限，需商用模型验证 |
| 8 | **测试覆盖率 ~5%** | 18 个单测 (decay_engine + event_bus)，核心模块目标 90% |
| 9 | **LLM 流式输出** | 语音延迟 ~2-5s，文字通道 ~5s。流式可降到 <1s 首 Token |

### 已完成的重要修复

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
