# EchoSoul - 你的 AI 虚拟陪伴伙伴

EchoSoul 是一个基于大语言模型的智能陪伴系统，旨在为用户提供温暖、自然、无评判的对话体验。无论你是感到孤独、需要倾诉，还是只想找个有趣的 AI 聊聊天，EchoSoul 都会用心倾听，并给予真诚的回应。

## ✨ 特性
- 🧠 基于大语言模型，理解自然语言情感
- 🎨 可自定义性格、语气和陪伴风格
- 📝 支持对话记忆，提供连续、个性化的交流
- 💬 轻量部署，快速接入


## 🎭 多角色AI伴侣系统
- ✨ 角色创建中心：用户可从0开始打造专属AI伴侣，自定义名称、性别、性格（外向/内向/幽默/温柔/理性）、MBTI类型、兴趣标签、说话风格、背景故事
- 📚 预设角色库：提供官方预设角色，分类包括“心灵抚慰型”、“陪伴成长型”、“趣味娱乐型”供快速上手
- 🌐 角色广场：用户可创建并分享角色给其他用户，形成UGC生态；支持作品展示与下载
- 🧑‍🎤 2D/3D 虚拟人形象：支持 Live2D 动态立绘与 VRM 3D 虚拟化身，实现面部表情同步、口型匹配与情绪驱动动画（喜悦、悲伤、惊讶等）。

## 🧠 情感记忆系统（核心创新）
- 🧬 双阶衰减情感记忆算法：指数→幂律双阶衰减 + 间隔自适应巩固 + 冷却期微增益策略
- 📋 事实层：存储基础信息（姓名、生日、喜好、讨厌的事物）
- 💖 情感层：记录对话的情感标签（开心、难过、焦虑）、情绪变化趋势
- 🤝 关系层：记录共同事件、重要时刻、关系里程碑
- 🗜️ 记忆摘要：定期将长期记忆压缩汇总，防止上下文过长的同时保留核心信息

## 📖 共创叙事系统
- 🎬 叙事起点推荐：系统智能推荐故事开篇，激发创作灵感
- 🌿 剧情分支选择：用户在关键节点选择走向，影响故事发展
- 🤖 AI 自适应生成：AI 实时续写，动态适配分支，确保叙事连贯
- 🎯 多结局见证：共同走向独特结局，每次体验都不同
- 📂 叙事存档与回放：保存完整故事，随时回顾精彩旅程
- 👥 多人叙事模式：邀请伙伴加入，共建共享奇妙故事世界

## 🎮 游戏化系统
- 🌱 养成系统：通过对话积累亲密度，解锁新对话话题、记忆容量扩容、专属互动动作
- 📋 每日任务：“早安问候”、“分享一天”等轻量任务
- 🏆 成就系统：记录聊天字数、累计天数、共同经历里程碑等成就
- 🎨 角色皮肤/主题：解锁不同的UI主题和角色外观

## ⏳ 时空异步伴生体验
- 📝 生活日志：用户离线时，AI 自动生成生活日志（今天做了什么、想到了用户什么、写了什么给用户）
- 🔄 跨设备同步：支持离线消息与跨设备同步，陪伴不中断
- ⏰ 陪伴时段：用户可自定义离线陪伴时间段，AI 在指定时段主动伴生


locust -f locustfile.py --host=http://127.0.0.1:8000

chroma run --host localhost --port 8000 --path ./chroma_data

celery -A app.celery_app worker --loglevel=info -P threads

uvicorn app.main:create_app --factory --host 127.0.0.1 --port 9000 --reload

uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 2
uvicorn app.main:create_app --host 127.0.0.1 --port 8000

uvicorn voice_companion_demo:app --host 127.0.0.1 --port 8000

$env:CHROMA_SERVER_AUTHN_PROVIDER=""; chroma run --path ./chroma_data

# 使用清华源安装
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 使用阿里源安装
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/


New-Item -Path . -Name ".gitignore" -ItemType File -Value ".env`n"

以后只需：

方式 1 — Makefile（推荐）：
make chroma    # 替代每次手输那一长串

方式 2 — PowerShell 一行：
$env:CHROMA_SERVER_AUTHN_PROVIDER=""; chroma run --path ./chroma_data

方式 3 — 根治（降级 chromadb，一劳永逸）：
pip install chromadb==0.5.23
这个版本没有鉴权，和之前正常工作的一样。

# 整体架构图

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


