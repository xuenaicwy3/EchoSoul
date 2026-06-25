"""
三层情感记忆向量化服务

将 user_facts（事实层）、emotion_records（情感层）、relationship_milestones（关系层）
从 PostgreSQL 同步到 ChromaDB，实现语义向量检索。

架构设计：
- 三层各自独立 Chroma 集合，语义空间天然分离
- 使用 PG 主键 + 前缀作为 Chroma 文档 ID，支持幂等 upsert
- 嵌入文本格式针对每层语义特点精心设计，最大化检索召回率
"""
import concurrent.futures
import json
import logging
import math
import random
import threading
import time as _time
from typing import List, Dict, Optional

from chromadb import HttpClient
from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings
from sqlalchemy import select

from app.config import Settings
from app.database import get_async_session
from app.models.db_models import UserFact, EmotionRecord, RelationshipMilestone

logger = logging.getLogger(__name__)

# 共享线程池：避免每次调用创建/销毁线程（嵌入超时 + LLM 兜底共用）
_SHARED_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="vecmem")


class ExternalAPIClient:
    """
    商用级外部 API 调用器：重试 + 指数退避 + 熔断 + 降级 四件套。

    用于 LLM 兜底路由和嵌入 API 的超时保护。不用于 Chroma 本地查询。

    退避公式: delay = base × multiplier^attempt ± jitter%
    示例 (base=1.0, multiplier=2.0, jitter=0.25):
      第0次失败 → 等待 1.0s ± 0.25s → 重试
      第1次失败 → 等待 2.0s ± 0.50s → 重试
      第2次失败 → 等待 4.0s ± 1.00s → 重试（若还有重试配额）
    """

    def __init__(self, name: str, max_retries: int = 2,
                 timeouts: tuple = (3.0, 5.0, 8.0),
                 backoff_base: float = 1.0,
                 backoff_multiplier: float = 2.0,
                 backoff_jitter: float = 0.25,
                 circuit_threshold: int = 5,
                 circuit_cooldown: float = 300.0):
        self._name = name
        self._max_retries = max_retries
        self._timeouts = timeouts
        self._backoff_base = backoff_base
        self._backoff_multiplier = backoff_multiplier
        self._backoff_jitter = backoff_jitter
        self._circuit_threshold = circuit_threshold
        self._circuit_cooldown = circuit_cooldown
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._total_calls = 0
        self._total_failures = 0
        self._total_retries = 0

    @property
    def circuit_open(self) -> bool:
        """
            检查熔断器当前是否处于打开（断路）状态。

        熔断器打开意味着系统在冷却时间内，所有调用请求都会被直接拒绝，
        以保护下游服务或避免持续无效重试。当熔断冷却时间结束后，熔断器自动关闭，
        恢复正常调用。

        Returns:
            True: 熔断器打开，当前不应发起任何实际调用。
            False: 熔断器关闭，可以正常调用。

        :return:
        """
        # 原理：比较当前单调时钟与熔断器恢复时间。
        # _circuit_open_until 是在触发熔断时设置的“未来某个时刻”。
        # 如果当前时间 < 该时刻，说明还在冷却期 → 熔断打开。
        # 如果当前时间 >= 该时刻，冷却期已过 → 熔断关闭。
        return _time.monotonic() < self._circuit_open_until

    def _backoff_delay(self, attempt: int) -> float:
        """
          计算第 attempt 次失败后的退避等待时间（含抖动）。

        退避策略：指数增长 + 随机抖动
          - 基础延迟 base 乘以 (乘数 ** 重试次数)，实现指数级退避。
          - 在此基础上加入随机抖动，避免多个客户端同时重试造成“惊群效应”。

        Args:
            attempt: 当前重试次数（从 0 开始），对应第 (attempt+1) 次重试。

        Returns:
            浮点数，本次重试前需要等待的秒数。
        """
        delay = self._backoff_base * (self._backoff_multiplier ** attempt)
        jitter = delay * self._backoff_jitter * (2.0 * random.random() - 1.0)
        return delay + jitter

    def call(self, fn, *args, **kwargs):
        """
        调用 fn(*args, **kwargs)，含重试+指数退避+熔断+降级 四件套。

        执行流程：
        1. 检查熔断 → 熔断中直接降级
        2. 第1次尝试 (timeout=3s)
           ├─ 成功 → 复位，返回
           └─ 失败 → 退避等待 1.0s±0.25s → 重试
        3. 第2次重试 (timeout=5s)
           ├─ 成功 → 复位，返回
           └─ 失败 → 退避等待 2.0s±0.5s → 重试
        4. 第3次重试 (timeout=8s)
           ├─ 成功 → 复位，返回
           └─ 失败 → 全部耗尽，触发熔断检查

        返回: fn 的返回值，或 None（降级）
        """
        # ============================
        # 1. 熔断快速失败检查
        # ============================
        # circuit_open: 熔断器是否处于打开状态（True 表示熔断中）
        # 若熔断，无论 fn 是什么，直接放弃调用，避免无效请求拖垮下游服务
        if self.circuit_open:  # 当前单调时钟 < 熔断恢复时间时间，熔断中 → 熔断中
            # 计算熔断剩余冷却时间：_circuit_open_until 是熔断结束的单调时钟时间
            remaining = self._circuit_open_until - _time.monotonic()
            logger.warning("[%s] 熔断中(剩余%.0fs)，跳过调用", self._name, remaining)
            # 降级返回 None，调用方需检查并处理 None 值
            return None

        # 记录最后一次失败的错误信息（用于最终日志）
        last_error = None
        # 总尝试次数 = 1 次初始调用 + 最大重试次数
        total_attempts = self._max_retries + 1

        # ============================
        # 2. 重试循环
        # ============================
        for attempt in range(total_attempts):
            # ---- 2.1 确定本次尝试的超时时间 ----
            # _timeouts 是一个列表，预设了每次尝试的超时秒数（如 [3, 5, 8]）
            # 若重试次数超过列表长度，使用最后一个时间
            timeout = (self._timeouts[attempt]
                       if attempt < len(self._timeouts)
                       else self._timeouts[-1])

            try:
                # ---- 2.2 在线程池中异步执行 fn ----
                # 使用全局共享线程池 _SHARED_EXECUTOR 提交任务，避免阻塞主线程，
                # 同时可利用 Future.result(timeout) 实现精确的超时控制
                # 共享线程池：避免每次调用创建/销毁线程（嵌入超时 + LLM 兜底共用）
                #_SHARED_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="vecmem")
                future = _SHARED_EXECUTOR.submit(fn, *args, **kwargs)
                # 阻塞等待结果，如果在 timeout 秒内未返回，抛出 TimeoutError
                result = future.result(timeout=timeout)

                # =====================
                # 成功处理
                # =====================
                # 获得锁，更新统计计数器
                with self._lock:
                    self._total_calls += 1          # 总调用次数 +1
                    self._consecutive_failures = 0  # 重置连续失败计数（恢复健康）
                # 如果不是第一次尝试成功，记录恢复日志
                if attempt > 0:
                    logger.info("[%s] 第%d次重试成功", self._name, attempt)
                # 返回真实结果
                return result

            except concurrent.futures.TimeoutError:
                # 超时异常：在设定的 timeout 秒内 fn 没有返回
                last_error = f"超时({timeout:.0f}s)"
                logger.warning("[%s] %d/%d 超时 %.0fs",
                             self._name, attempt + 1, total_attempts, timeout)
            except Exception as e:
                # 其他任何异常（网络错误、服务拒绝、序列化错误等）
                # 截断错误信息前100字符，防止日志污染
                last_error = str(e)[:100]
                logger.warning("[%s] %d/%d 失败: %s",
                             self._name, attempt + 1, total_attempts, last_error)

            # ---- 2.3 退避等待（最后一次失败后不等待） ----
            # 如果不是最后一次尝试，则在重试前等待一段时间
            if attempt < total_attempts - 1:
                # 根据当前重试次数计算退避延迟（通常带随机抖动）
                delay = self._backoff_delay(attempt)
                logger.info("[%s] 退避 %.1fs 后重试 (%d/%d)",
                          self._name, delay, attempt + 2, total_attempts)
                # 记录重试次数统计
                with self._lock:
                    self._total_retries += 1
                # 挂起当前线程，让出 CPU，等待后再次循环重试
                _time.sleep(delay)

        # ============================
        # 3. 全部重试均已失败，进行失败统计及熔断检查
        # ============================
        # 注意：这里加锁保护计数器和熔断状态的原子性更新
        with self._lock:
            self._total_calls += 1            # 本次调用计数 +1
            self._total_failures += 1          # 总失败次数 +1（用于计算失败率）
            self._consecutive_failures += 1    # 连续失败计数 +1

            # 检查是否触发熔断：连续失败次数 >= 预设阈值
            if self._consecutive_failures >= self._circuit_threshold:  # 3
                # 设置熔断恢复时间：当前单调时钟 + 冷却时长
                self._circuit_open_until = _time.monotonic() + self._circuit_cooldown
                logger.error("[%s] 熔断触发! 连续失败%d次 冷却%.0fs",
                           self._name, self._consecutive_failures, self._circuit_cooldown)
        # 最终失败日志，输出最后一次错误原因
        logger.error("[%s] 彻底失败(已重试%d次): %s", self._name, self._max_retries, last_error)
        # 降级：返回 None，表示本次调用彻底失败
        return None

    def stats(self) -> dict:
        return {
            "name": self._name,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_retries": self._total_retries,
            "consecutive_failures": self._consecutive_failures,
            "circuit_open": self.circuit_open,
        }

# 三层检索的路由关键词：帮助快速判断用户消息属于哪个记忆层的语义空间
_FACT_SIGNALS = [ # 静态属性关键词
    "我是", "我叫", "我的", "喜欢", "讨厌", "生日", "名字", "年龄",
    "工作", "职业", "住在", "宠物", "爱好", "兴趣", "擅长", "不会",
    "学过", "毕业", "老家", "家里", "爸妈", "朋友", "同学",
]
_EMOTION_SIGNALS = [ # 情感维度关键词
    "感觉", "心情", "开心", "难过", "生气", "害怕", "焦虑", "兴奋",
    "无聊", "失落", "情绪", "好累", "很烦", "想哭", "感动", "紧张",
    "期待", "失望", "后悔", "孤独", "想念","哈哈","加油","伤心"
]
_MILESTONE_SIGNALS = [ # 关系历史关键词
    "记得", "上次", "以前", "曾经", "一起", "第一次", "那天", "当时",
    "回忆", "还记得", "我们", "那天晚上", "那年", "认识", "见面",
    "刚认识", "之前说过", "你答应", "你答应过",
]


class MemoryRetrievalRouter:
    """
    商用级三层记忆路由器：关键词+嵌入+LLM 三级路由，自动决定检索哪几层。

    路由管线（按优先级）：
    1. 关键词快速匹配 — 零成本 ~10μs，命中明确信号词直接打分
    2. 嵌入锚点相似度 — 复用已有查询向量，零额外 API 调用
    3. LLM 兜底分类 — 仅在规则路由不确定时触发，精确分类 + 对话深度感知
    4. 所有失败路径均有降级：LLM挂 → 规则结果，规则无结果 → 激活最高分层

    决策因子（按优先级，不再依赖对话轮数硬性触发）：
    1. 语义得分分布 — 阈值过滤 + 跨层共振检测 + 安全网扩展
    2. 对话深度弱先验 — 仅微调阈值(±0.03)，绝不强制多层检索
    3. LLM 兜底 — 仅在得分分布高度不确定时触发
    4. 所有失败路径降级：LLM挂→规则结果，规则无结果→最高分层
    """

    # 路由阈值
    ACTIVATION_THRESHOLD = 0.15        # 基础激活阈值
    ACTIVATION_THRESHOLD_DEEP = 0.12   # 深度对话(≥30轮)微调阈值
    LLM_FALLBACK_MIN_SCORE = 0.15      # 最高分低于此→LLM兜底
    AMBIGUITY_GAP = 0.04               # 前两名差距小于此→语义模糊（收紧到0.04）
    CROSS_LAYER_RESONANCE_SPREAD = 0.12 # 三层得分极差小于此→跨层共振，扩到所有高分
    SINGLE_LAYER_SAFETY_NET = 0.30     # 仅激活1层且低于此分→吸纳次高层
    DIFFUSE_LLM_TOP_THRESHOLD = 0.25   # 均匀分布+最高分低于此→LLM兜底
    CONVERSATION_DEEP_PRIOR = 30       # 对话≥30轮才施加弱先验

    def __init__(self, embeddings, settings: Settings):
        self._embeddings = embeddings
        self._settings = settings
        self._layer_anchors: Dict[str, List[float]] = {}
        self._anchors_ready = False
        self._llm = None
        # LLM 客户端：重试2次(3s→5s→8s)，退避1s→2s±25%抖动，连续失败5次熔断5分钟
        self._llm_client = ExternalAPIClient(
            name="router-llm",
            max_retries=2,
            timeouts=(3.0, 5.0, 8.0),
            backoff_base=1.0,
            backoff_multiplier=2.0,
            backoff_jitter=0.25,
            circuit_threshold=5,
            circuit_cooldown=300.0,
        )

    # ==================== 初始化 ====================

    def _ensure_anchors(self):
        """延迟初始化语义锚点向量（含超时保护）"""
        if self._anchors_ready:
            return
        anchors = {
            "facts": "用户个人信息 姓名 年龄 喜好 职业 属性 特征",
            "emotions": "用户心情 情绪 感受 感觉 心理状态 情感",
            "milestones": "共同经历 回忆 关系发展 纪念日 事件 约定",
        }
        t0 = _time.monotonic()
        for layer, text in anchors.items():
            embedding = self._embeddings.embed_query(text)
            if embedding is not None:
                self._layer_anchors[layer] = embedding
        self._anchors_ready = True
        logger.info("锚点向量初始化完成 耗时=%.0fms layers=%s",
                    (_time.monotonic() - t0) * 1000,
                    {k: f"dim={len(v)}" for k, v in self._layer_anchors.items()})

    def _ensure_llm(self):
        """延迟初始化 LLM 兜底模型"""
        if self._llm is not None:
            return
        self._llm = init_chat_model(
            model=self._settings.LLM_MODEL,
            model_provider="openai",
            temperature=0.0,
            max_tokens=30,
            api_key=self._settings.DASHSCOPE_API_KEY,
            base_url=self._settings.DASHSCOPE_BASE_URL,
        )
        logger.info("路由 LLM 兜底模型就绪: %s", self._settings.LLM_MODEL)

    # ==================== 评分计算 ====================

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        """
        计算两个向量 a 和 b 的余弦相似度。

        余弦相似度衡量两个向量的方向一致性，值域为 [-1, 1]：
          -  1 表示方向完全相同；
          -  0 表示正交（不相关）；
          - -1 表示方向完全相反。
        在文本嵌入中，通常只关心非负相似度，因此底层实现也会将零向量情况返回 0.0。

        Args:
            a: 第一个浮点数向量（如查询文本的嵌入）。
            b: 第二个浮点数向量（如某一记忆层的锚点嵌入）。

        Returns:
            两个向量的余弦相似度。若任一向量为零向量（模长为0），返回 0.0。
        """
        # 计算点积：a·b = Σ(a_i * b_i)
        dot = sum(x * y for x, y in zip(a, b))

        # 计算向量 a 的模长（L2 范数）：||a|| = √(Σ(a_i^2))
        na = math.sqrt(sum(x * x for x in a))

        # 计算向量 b 的模长（L2 范数）：||b|| = √(Σ(b_i^2))
        nb = math.sqrt(sum(x * x for x in b))

        # 余弦相似度 = 点积 / (||a|| * ||b||)
        # 添加零除保护：如果任一向量模长为 0，直接返回 0.0，避免除零错误
        return dot / (na * nb) if na and nb else 0.0

    @staticmethod
    def _keyword_score(text: str, signals: List[str]) -> float:
        """
        计算文本中包含的信号词命中得分（静态方法，不依赖类实例）。

        遍历给定的信号词列表，统计有多少个不同的信号词作为子串出现在 text 中，
        每个命中的词贡献 0.25 分，总分上限为 1.0。

        Args:
            text: 用户输入的待检测文本。
            signals: 信号词列表（例如 ["喜欢", "讨厌", ...]）。

        Returns:
            介于 0.0 到 1.0 之间的浮点数分数。
        """
        # 用生成器表达式检查每个信号词是否为 text 的子串（简单字符串包含）
        # 每次命中生成 1，sum 求和得到总命中种类数（而非出现次数）
        hits = sum(1 for s in signals if s in text)
        return min(1.0, hits * 0.25)

    def route(self, query: str, query_embedding: List[float]) -> dict:
        """
        路由评分：关键词40% + 嵌入锚点向量60%。 综合关键词命中和嵌入锚点相似度，判断查询属于哪个记忆层。

        评分由两部分加权组成：
        - 关键词得分（权重 40%）：基于预定义的信号词表，统计 query 中包含的信号词数量。
        - 嵌入锚点得分（权重 60%）：计算 query 嵌入向量与各记忆层锚点向量的余弦相似度，
          并归一化到 [0, 1] 区间。

        返回: {
            "scores": {"facts": 0.72, "emotions": 0.15, "milestones": 0.08},
            "top_layer": "facts",
            "top_score": 0.72,
            "gap": 0.57,       # 第一名与第二名差距
            "sorted": [("facts", 0.72), ("emotions", 0.15), ("milestones", 0.08)]
        }
        """
        # 1. 锚点向量是每个记忆层的参考嵌入，用于计算语义相似度。
        self._ensure_anchors() # 延迟初始化锚点向量

        # 2. 计算关键词命中得分（0.0 ~ 1.0）
        # 分别用三个记忆层的信号词表对 query 进行关键词匹配，得到 0~1 的得分。
        kw = {
            "facts": self._keyword_score(query, _FACT_SIGNALS),
            "emotions": self._keyword_score(query, _EMOTION_SIGNALS),
            "milestones": self._keyword_score(query, _MILESTONE_SIGNALS),
        }
        # 3. 计算嵌入锚点余弦相似度（原始值 -1 ~ 1）
        emb_raw = {
            "facts": self._cosine(query_embedding, self._layer_anchors["facts"]),
            "emotions": self._cosine(query_embedding, self._layer_anchors["emotions"]),
            "milestones": self._cosine(query_embedding, self._layer_anchors["milestones"]),
        }
        # 归一化嵌入得分到 [0,1] 数学公式：新值 = (原始值 - 最小值) / (最大值 - 最小值)
        # 4. 对嵌入得分进行 Min-Max 归一化到 [0, 1]
        vals = list(emb_raw.values())
        vmin, vmax = min(vals), max(vals)
        emb = {}
        if vmax > vmin:
            # 标准 Min-Max 归一化: (x - min) / (max - min)
            for k in emb_raw:
                emb[k] = (emb_raw[k] - vmin) / (vmax - vmin)
        else:
            #所有值都相等（包括全为 0 的情况）：无法区分，那就全部设为 1.0
            emb = {k: 1.0 for k in emb_raw}

        # 融合得分
        scores = {k: 0.4 * kw[k] + 0.6 * emb[k] for k in kw}
        # 按得分从高到低排序
        sorted_layers = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_layer, top_score = sorted_layers[0]
        # 计算差距 第一名得分 - 第二名得分  本质就是在问：“最大的那个分数，是不是稳赢第二名？”
        gap = sorted_layers[0][1] - sorted_layers[1][1] if len(sorted_layers) >= 2 else 1.0

        logger.info(
            "路由评分: %s top=%.3f gap=%.3f | kw: %s | emb: %s",
            {k: round(v, 3) for k, v in scores.items()},
            top_score, gap,
            {k: round(v, 2) for k, v in kw.items()},
            {k: round(v, 3) for k, v in emb.items()},
        )
        return {"scores": scores, "top_layer": top_layer, "top_score": top_score,
                "gap": gap, "sorted": sorted_layers}

    # ==================== LLM 兜底（含重试+熔断） ====================

    def _llm_classify(self, query: str, rule_result: list) -> Optional[List[str]]:
        """
        LLM 兜底分类 —— 通过 ExternalAPIClient 调用，含重试+熔断+降级。

        仅在规则路由高度不确定时调用。Prompt 聚焦查询本身语义维度。
        """
        self._ensure_llm()

        prompt = (
            "你是一个【资深情感记忆检索路由器专家】。根据用户消息，判断需要检索哪些记忆层。\n\n"
            "【三层记忆定义】\n"
            "- facts: 用户个人信息(姓名/喜好/职业/生日/习惯等静态属性)\n"
            "- emotions: 用户情感状态(心情/情绪变化/感受/态度等情感维度)\n"
            "- milestones: 关系发展事件(共同经历/回忆/约定/重要时刻等关系历史)\n\n"
            "【路由规则】\n"
            "- 询问/提及个人信息、属性、习惯 → facts\n"
            "- 表达/询问感受、心情、情绪、态度 → emotions\n"
            "- 提及过去、回忆、共同经历、约定 → milestones\n"
            "- 消息涉及多个维度且难以判断 → 多选相关层\n\n"
            f"用户消息: {query}\n\n"
            "只输出JSON数组(不含任何其他文字)。如: [\"facts\"] / [\"facts\",\"emotions\"] / [\"facts\",\"emotions\",\"milestones\"]"
        )

        response = self._llm_client.call(self._llm.invoke, prompt)
        if response is None:
            # 重试耗尽或熔断中 → 降级
            logger.warning("LLM 兜底降级: 规则结果=%s (stats=%s)",
                          rule_result, self._llm_client.stats())
            return None

        try:
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            layers = json.loads(raw)
            valid = [l for l in layers if l in ("facts", "emotions", "milestones")]
            if valid:
                logger.info("LLM 兜底结果: %s (规则结果: %s)", valid, rule_result)
                return valid
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning("LLM 兜底解析失败: raw=%s error=%s", raw[:80], e)
        return None

    # ==================== 核心决策（多因子） ====================

    def _analyze_score_distribution(self, sorted_layers: list) -> dict:
        """
        分析三层得分的分布模式，识别查询的语义复杂度。

        输入 sorted_layers 已经是按得分从高到低排列的 (层名, 得分) 列表，
        返回:
          spread: 最高分与最低分的差值（极差），范围 0~1。
            - "concentrated" : 单层显著领先，其它层分数很低。
            - "dual"         : 前两名非常接近，第三名落后。
            - "diffuse"      : 三层得分都很接近，没有明显分层。
          single_dominant: 布尔值，True 表示可仅依赖单层检索。
        """
        # 1. 提取三个得分（已经按降序排列）
        # sorted_layers 示例: [("facts", 0.72), ("emotions", 0.68), ("milestones", 0.10)]
        scores = [s for _, s in sorted_layers]  # 得到 [0.72, 0.68, 0.10]

        # 2. 计算极差 (spread)：第一名与最后一名的分数差
        # 如果列表长度不足 3（防御性代码），强制设为 1.0 表示完全分散。
        # 正常情况下 spread 值域为 [0, 1]。
        spread = scores[0] - scores[-1] if len(scores) >= 3 else 1.0

        # 3. 根据两个阈值判断分布模式
        # CROSS_LAYER_RESONANCE_SPREAD: 跨层共振极差阈值。0.25
        #     跨层共振极差阈值。如果三层最高与最低分差距 ≤ 0.25，
        #     表示查询与所有三个记忆层都有显著语义关联，记忆需求可能是
        #     跨维度混合的，这时路由无法也不应该只选一层。
        # AMBIGUITY_GAP: 模糊间隙阈值。0.12
        #     模糊间隙阈值。当极差已超过 0.25（排除均匀情况），但
        #     第一名与第二名的分差 ≤ 0.12，说明前两名咬得极紧，此时
        #     单纯依赖第一名可能会漏掉第二名所代表的重要记忆。

        if spread <= self.CROSS_LAYER_RESONANCE_SPREAD:  # 0.25
            # 三层得分几乎一样，例如 # 例如 [0.55, 0.45, 0.40] → spread = 0.25
            pattern = "diffuse"       # 三层得分接近 → 查询涉及多个维度 → 需要跨层检索记忆
        elif len(sorted_layers) >= 2 and (scores[0] - scores[1]) <= self.AMBIGUITY_GAP: # 0.12
            # 例如 [0.65, 0.55, 0.15] → 前两名差 0.10，极差 0.50。
            pattern = "dual"          # 前两名接近 → 双峰
        else:
            # 情况 C：既不均匀，前两名又有明显差距（>0.12）。
            # 例如 [0.80, 0.35, 0.15] → 第一名领先第二名 0.45，极差 0.65。
            # 语义解释：路由高度自信，查询明确属于某一个记忆层，
            pattern = "concentrated"  # 单层显著领先

        return {
            "spread": spread,
            "pattern": pattern,
            "single_dominant": pattern == "concentrated",
        }

    def decide(self, query: str, query_embedding: List[float],
               conversation_rounds: int = 0) -> list:
        """
        商用级多因子路由决策（唯一公开入口）。

        决策管线:
        1. route评分 → 语义得分
        2. 得分分布分析 → 跨层共振/双峰/集中
        3. 对话深度弱先验 → 仅微调阈值(≥30轮: 0.15→0.12)
        4. 阈值过滤 + 分布扩张 + 安全网
        5. LLM兜底 → 仅在得分分布高度不确定时触发
        6. 降级保障 → 至少激活最高分层

        对话轮数角色（明确定位）：
        - 仅作为弱先验：≥30轮时阈值从0.15微调到0.12
        - 不作为硬触发器，不会出现"聊了15轮就全3层"
        - 真正决定层数的是：查询语义 + 得分分布 + 跨层共振
        """
        # === 因子1: route评分 ===
        t0 = _time.monotonic()
        route_result = self.route(query, query_embedding)
        top_score = route_result["top_score"]
        gap = route_result["gap"]
        sorted_layers = route_result["sorted"]
        scores = route_result["scores"]
        # "scores": {"facts": 0.72, "emotions": 0.15, "milestones": 0.08},
        logger.info(f"路由评分：scores: {scores}")
        logger.info("路由评分: %s (%.3f s)", scores, _time.monotonic() - t0)

        # === 因子2: 得分分布分析 ===
        distribution = self._analyze_score_distribution(sorted_layers)
        logger.info("得分分布: %s (%.3f s)", distribution, _time.monotonic() - t0)

        # === 因子3: 对话深度弱先验 → 微调阈值 ===
        threshold = self.ACTIVATION_THRESHOLD  # 0.15
        if conversation_rounds >= self.CONVERSATION_DEEP_PRIOR: # 50
            threshold = self.ACTIVATION_THRESHOLD_DEEP # 0.12

        # === 因子1: 阈值过滤 ===
        active = []
        for layer, score in sorted_layers:
            if score >= threshold:
                active.append(layer)

        # === 因子4: 分布驱动扩张/收缩 ===
        # 在前面的因子（阈值过滤等）得到 active 列表后，本因子根据得分分布模式
        # 对 active 做进一步动态调整，确保检索层数既不过度也不遗漏。
        #
        # 核心思想：
        # - 若查询语义分散，应扩大检索范围（扩张）。
        # - 若前两名难分伯仲，应至少激活这两层（补全）。
        # - 若虽只有一层入选但得分偏低，为避免单层覆盖不足，引入次高层作为兜底（安全网）。
        #
        # 这样可以在不同分布下平衡准确率与召回率，避免过度自信或模糊时信息缺失。

        # 4a. 跨层共振：三层得分接近 → 用户消息语义复杂，扩到所有阈值以上层
        if distribution["pattern"] == "diffuse" and len(active) >= 2:
            # - pattern == "diffuse" 表示极差 <= 0.25，三层分数很均匀，查询跨维度。
            # 三层都接近 → 全激活所有绝对分数 >= threshold（弱先验阀值） 的层
            active = [l for l, s in sorted_layers if s >= threshold]

        # 4b. 双峰模式：前两名接近 → 两层都激活
        elif distribution["pattern"] == "dual" and len(active) < 2: # 只激活了1层
            # 动作：若第二名得分 ≥ threshold * 0.8（即不低于阈值的80%），则将其补入 active。
            if len(sorted_layers) >= 2 and sorted_layers[1][1] >= threshold * 0.8:
                active.append(sorted_layers[1][0])

        # 4c. 单层低分安全网：仅1层但得分不高 → 吸纳次高层
        if len(active) == 1 and top_score < self.SINGLE_LAYER_SAFETY_NET: # 安全网阈值为 0.3
            # 动作：检查第二名得分是否 ≥ threshold * 0.7（更低的放宽比例），
            # 如果是，则将第二名也加入 active，形成双路兜底，避免因单层信号弱导致回答空洞。
            second_best = sorted_layers[1]
            if second_best[1] >= threshold * 0.7:
                active.append(second_best[0])
                logger.info("安全网扩展: %s(%.3f) → +%s(%.3f)",
                          sorted_layers[0][0], top_score, second_best[0], second_best[1])

        # === 兜底：至少激活最高分层 ===
        if not active:
            active.append(sorted_layers[0][0])

        # === 因子5: LLM 兜底触发检测 ===
        # 前面的因子已经尽力通过规则（分数、分布、阈值等）决定了 active 层集合，
        # 但有些情况下规则结果仍可能不可靠。这里设置三个“不确定性”条件，
        # 只要满足任一条件，就触发 LLM 进行更智能的层分类，用语义理解兜底。

        need_llm = False
        llm_reason = "" # 记录触发 LLM 的原因，用于日志追踪

        # 条件1：最高分过低 → 整体置信度不足
        if top_score < self.LLM_FALLBACK_MIN_SCORE: # 0.15
            # 最高分都低于0.15 → 规则路由不自信 → 交给 LLM 重新理解查询
            need_llm = True
            llm_reason = f"置信度过低(max={top_score:.3f}<{self.LLM_FALLBACK_MIN_SCORE})"

        # 条件2：均匀分布 + 最高分也不高 → 查询跨层且模糊
        elif distribution["pattern"] == "diffuse" and top_score < self.DIFFUSE_LLM_TOP_THRESHOLD: # 0.25
            # 均匀分布+最高分也不高 → 规则路由在三个层上都没有突出的把握，选出的 active 可能并不可靠 → 同样转 LLM 判断
            need_llm = True
            llm_reason = f"均匀分布+低分(spread={distribution['spread']:.3f} top={top_score:.3f}<{self.DIFFUSE_LLM_TOP_THRESHOLD})"

        # 条件3：双峰极窄 → 前两名几乎平手，规则无法抉择
        elif distribution["pattern"] == "dual" and gap < 0.03:
            # 双峰极窄 → 近乎并列第一 → 极端模糊的情况交给 LLM 深度分析
            need_llm = True
            llm_reason = f"双峰极窄(gap={gap:.3f}<0.03)"

        # 执行 LLM 兜底
        if need_llm:
            # 记录触发原因，便于监控 LLM 兜底频率是否在合理范围
            logger.info("触发 LLM 兜底: %s | 规则结果=%s (阈值=%.2f)", llm_reason, active, threshold)
            llm_layers = self._llm_classify(query, active)

            # 如果 LLM 成功返回结果（非 None），则采用 LLM 的决定，并直接返回，不再继续后续逻辑
            if llm_layers is not None:
                elapsed = (_time.monotonic() - t0) * 1000
                logger.info("路由决策(llm): layers=%s 分布=%s rounds=%d 耗时=%.0fms",
                            llm_layers, distribution["pattern"], conversation_rounds, elapsed)
                return llm_layers
            logger.info("LLM 兜底失败，降级为规则结果: %s", active)

        # 没有触发 LLM 兜底（或 LLM 失败降级），最终使用规则结果 active 作为最终检索层集合
        elapsed = (_time.monotonic() - t0) * 1000
        logger.info("路由决策: layers=%s 分布=%s 阈值=%.2f top=%.3f gap=%.3f rounds=%d 耗时=%.0fms",
                    active, distribution["pattern"], threshold, top_score, gap,
                    conversation_rounds, elapsed)
        return active


class VectorMemoryService:
    """三层情感记忆的向量化存储与检索服务"""

    def __init__(self, settings: Settings):
        self.settings = settings

        # 嵌入模型（与对话记忆共用 text-embedding-v4）
        self.embeddings = DashScopeEmbeddings(
            model=settings.EMBED_MODEL,
            dashscope_api_key=settings.DASHSCOPE_API_KEY,
        )

        # 连接 Chroma HTTP 服务（与对话记忆共用 localhost:8000）
        self.client = HttpClient(host="localhost", port=8000)

        # 三个独立集合，分别对应三层记忆
        self.facts_col = self.client.get_or_create_collection(
            name=settings.VECTOR_FACTS_COL,
            metadata={"hnsw:space": "cosine"}
        )
        self.emotions_col = self.client.get_or_create_collection(
            name=settings.VECTOR_EMOTIONS_COL,
            metadata={"hnsw:space": "cosine"}
        )
        self.milestones_col = self.client.get_or_create_collection(
            name=settings.VECTOR_MILESTONES_COL,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(
            "向量记忆服务初始化完成 事实=%d 情感=%d 里程碑=%d",
            self.facts_col.count(), self.emotions_col.count(), self.milestones_col.count()
        )

        # 智能路由器（延迟初始化锚点，避免启动时 API 调用）
        self._router = MemoryRetrievalRouter(self.embeddings, settings)


    # ==================== 嵌入文本构造 ====================

    @staticmethod
    def _fact_text(key: str, value: str) -> str:
        """事实层嵌入文本：'用户的{key}是{value}'"""
        return f"用户的{key}是{value}"

    @staticmethod
    def _emotion_text(label: str, message: Optional[str]) -> str:
        """情感层嵌入文本：'用户感到{label}，他说：{message}'"""
        if message:
            return f"用户感到{label}，他说：{message}"
        return f"用户感到{label}"

    @staticmethod
    def _milestone_text(event_type: str, event: str, details: Optional[str]) -> str:
        """关系层嵌入文本：'[{event_type}] {event}，详情：{details}'"""
        base = f"[{event_type}] {event}"
        if details:
            base += f"，详情：{details}"
        return base

    # ==================== 单条实时同步（PG 写入后即时调用） ====================

    def sync_fact(self, fact: UserFact) -> None:
        """同步单条事实到 ChromaDB"""
        if not fact.id:
            logger.warning("sync_fact 跳过：fact.id 为空")
            return
        try:
            text = self._fact_text(fact.key, fact.value)
            embedding = self.embeddings.embed_query(text)
            self.facts_col.upsert(
                ids=[f"fact_{fact.id}"],
                documents=[text],
                metadatas=[{
                    "user_id": fact.user_id,
                    "role_type": fact.role_type,
                    "key": fact.key,
                    "source": fact.source,
                    "strength": fact.strength,
                    "salience": fact.salience,
                    "status": fact.status,
                }],
                embeddings=[embedding]
            )
            logger.info("sync_fact OK: id=%s key=%s strength=%.2f salience=%.3f status=%s",
                        fact.id, fact.key, fact.strength, fact.salience, fact.status)
        except Exception as e:
            logger.error("sync_fact 失败 fact_id=%s: %s", fact.id, e)

    def sync_emotion(self, record: EmotionRecord) -> None:
        """同步单条情绪记录到 ChromaDB"""
        if not record.id:
            logger.warning("sync_emotion 跳过：record.id 为空")
            return
        try:
            text = self._emotion_text(record.label, record.message)
            embedding = self.embeddings.embed_query(text)
            self.emotions_col.upsert(
                ids=[f"emotion_{record.id}"],
                documents=[text],
                metadatas=[{
                    "user_id": record.user_id,
                    "role_type": record.role_type,
                    "label": record.label,
                    "score": record.score,
                    "strength": record.strength,
                    "status": record.status,
                }],
                embeddings=[embedding]
            )
            logger.info("sync_emotion OK: id=%s label=%s score=%.2f strength=%.2f",
                        record.id, record.label, record.score, record.strength)
        except Exception as e:
            logger.error("sync_emotion 失败 emotion_id=%s: %s", record.id, e)

    def sync_milestone(self, milestone: RelationshipMilestone) -> None:
        """同步单条里程碑到 ChromaDB"""
        if not milestone.id:
            logger.warning("sync_milestone 跳过：milestone.id 为空")
            return
        try:
            text = self._milestone_text(milestone.event_type, milestone.event, milestone.details)
            embedding = self.embeddings.embed_query(text)
            self.milestones_col.upsert(
                ids=[f"milestone_{milestone.id}"],
                documents=[text],
                metadatas=[{
                    "user_id": milestone.user_id,
                    "role_type": milestone.role_type,
                    "event_type": milestone.event_type,
                    "strength": milestone.strength,
                    "status": milestone.status,
                }],
                embeddings=[embedding]
            )
            logger.info("sync_milestone OK: id=%s event_type=%s strength=%.2f",
                        milestone.id, milestone.event_type, milestone.strength)
        except Exception as e:
            logger.error("sync_milestone 失败 milestone_id=%s: %s", milestone.id, e)

    # ==================== 批量全量同步（首次初始化 / 修复数据缺口） ====================

    async def sync_all_facts(self, user_id: str, role_type: str) -> int:
        """
        从 PostgreSQL 全量同步该用户-角色的所有活跃事实到 ChromaDB。
        返回同步条数。
        """
        try:
            session = get_async_session()
        except RuntimeError:
            logger.warning("sync_all_facts: 无法获取数据库会话")
            return 0
        async with session() as s:
            result = await s.execute(
                select(UserFact).where(
                    UserFact.user_id == user_id,
                    UserFact.role_type == role_type,
                    UserFact.status == "active"
                )
            )
            facts = result.scalars().all()

        if not facts:
            return 0

        ids = []
        documents = []
        metadatas = []
        for f in facts:
            ids.append(f"fact_{f.id}")
            documents.append(self._fact_text(f.key, f.value))
            metadatas.append({
                "user_id": f.user_id, "role_type": f.role_type,
                "key": f.key, "source": f.source,
                "strength": f.strength, "salience": f.salience, "status": f.status,
            })

        try:
            embeddings = self.embeddings.embed_documents(documents)
            self.facts_col.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
            logger.info("sync_all_facts: %d 条已同步", len(facts))
            return len(facts)
        except Exception as e:
            logger.error("sync_all_facts 失败: %s", e)
            return 0

    async def sync_all_emotions(self, user_id: str, role_type: str) -> int:
        """从 PostgreSQL 全量同步该用户-角色的所有活跃情绪到 ChromaDB"""
        try:
            session = get_async_session()
        except RuntimeError:
            return 0
        async with session() as s:
            result = await s.execute(
                select(EmotionRecord).where(
                    EmotionRecord.user_id == user_id,
                    EmotionRecord.role_type == role_type,
                    EmotionRecord.status == "active"
                )
            )
            records = result.scalars().all()

        if not records:
            return 0

        ids = []
        documents = []
        metadatas = []
        for r in records:
            ids.append(f"emotion_{r.id}")
            documents.append(self._emotion_text(r.label, r.message))
            metadatas.append({
                "user_id": r.user_id, "role_type": r.role_type,
                "label": r.label, "score": r.score,
                "strength": r.strength, "status": r.status,
            })

        try:
            embeddings = self.embeddings.embed_documents(documents)
            self.emotions_col.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
            logger.info("sync_all_emotions: %d 条已同步", len(records))
            return len(records)
        except Exception as e:
            logger.error("sync_all_emotions 失败: %s", e)
            return 0

    async def sync_all_milestones(self, user_id: str, role_type: str) -> int:
        """从 PostgreSQL 全量同步该用户-角色的所有活跃里程碑到 ChromaDB"""
        try:
            session = get_async_session()
        except RuntimeError:
            return 0
        async with session() as s:
            result = await s.execute(
                select(RelationshipMilestone).where(
                    RelationshipMilestone.user_id == user_id,
                    RelationshipMilestone.role_type == role_type,
                    RelationshipMilestone.status == "active"
                )
            )
            milestones = result.scalars().all()

        if not milestones:
            return 0

        ids = []
        documents = []
        metadatas = []
        for m in milestones:
            ids.append(f"milestone_{m.id}")
            documents.append(self._milestone_text(m.event_type, m.event, m.details))
            metadatas.append({
                "user_id": m.user_id, "role_type": m.role_type,
                "event_type": m.event_type,
                "strength": m.strength, "status": m.status,
            })

        try:
            embeddings = self.embeddings.embed_documents(documents)
            self.milestones_col.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
            logger.info("sync_all_milestones: %d 条已同步", len(milestones))
            return len(milestones)
        except Exception as e:
            logger.error("sync_all_milestones 失败: %s", e)
            return 0

    async def sync_all_layers(self, user_id: str, role_type: str) -> Dict[str, int]:
        """全量同步三层记忆，返回各层同步条数"""
        facts_n = await self.sync_all_facts(user_id, role_type)
        emotions_n = await self.sync_all_emotions(user_id, role_type)
        milestones_n = await self.sync_all_milestones(user_id, role_type)
        return {"facts": facts_n, "emotions": emotions_n, "milestones": milestones_n}

    # ==================== 删除 ====================

    def delete_fact(self, fact_id: int) -> None:
        """从 ChromaDB 删除指定事实"""
        try:
            self.facts_col.delete(ids=[f"fact_{fact_id}"])
        except Exception as e:
            logger.error("delete_fact 失败 fact_id=%s: %s", fact_id, e)

    def delete_emotion(self, emotion_id: int) -> None:
        """从 ChromaDB 删除指定情绪记录"""
        try:
            self.emotions_col.delete(ids=[f"emotion_{emotion_id}"])
        except Exception as e:
            logger.error("delete_emotion 失败 emotion_id=%s: %s", emotion_id, e)

    def delete_milestone(self, milestone_id: int) -> None:
        """从 ChromaDB 删除指定里程碑"""
        try:
            self.milestones_col.delete(ids=[f"milestone_{milestone_id}"])
        except Exception as e:
            logger.error("delete_milestone 失败 milestone_id=%s: %s", milestone_id, e)

    # ==================== 三层检索 ====================

    def retrieve_facts(self, user_id: str, role_type: str,
                       query_embedding: List[float], top_k: int = None) -> List[Dict]:
        """从事实层检索相关记忆"""
        if top_k is None:
            top_k = self.settings.VECTOR_TOP_K_FACTS
        try:
            results = self.facts_col.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={"$and": [{"user_id": user_id}, {"role_type": role_type}]},
                include=["documents", "metadatas", "distances"]
            )
            parsed = self._parse_results(results, "fact")
            logger.info("事实层检索: user=%s role=%s top_k=%d 命中=%d",
                        user_id, role_type, top_k, len(parsed))
            if parsed:
                for i, p in enumerate(parsed):
                    logger.info("  事实[%d] sim=%.4f text=%s", i, p["similarity"], p["text"][:80])
            return parsed
        except Exception as e:
            logger.error("retrieve_facts 失败: %s", e)
            return []

    def retrieve_emotions(self, user_id: str, role_type: str,
                          query_embedding: List[float], top_k: int = None) -> List[Dict]:
        """从情感层检索相关记忆"""
        if top_k is None:
            top_k = self.settings.VECTOR_TOP_K_EMOTIONS
        try:
            results = self.emotions_col.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={"$and": [{"user_id": user_id}, {"role_type": role_type}]},
                include=["documents", "metadatas", "distances"]
            )
            parsed = self._parse_results(results, "emotion")
            logger.info("情感层检索: user=%s role=%s top_k=%d 命中=%d",
                        user_id, role_type, top_k, len(parsed))
            if parsed:
                for i, p in enumerate(parsed):
                    logger.info("  情感[%d] sim=%.4f text=%s", i, p["similarity"], p["text"][:80])
            return parsed
        except Exception as e:
            logger.error("retrieve_emotions 失败: %s", e)
            return []

    def retrieve_milestones(self, user_id: str, role_type: str,
                            query_embedding: List[float], top_k: int = None) -> List[Dict]:
        """从关系层检索相关记忆"""
        if top_k is None:
            top_k = self.settings.VECTOR_TOP_K_MILESTONES
        try:
            results = self.milestones_col.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={"$and": [{"user_id": user_id}, {"role_type": role_type}]},
                include=["documents", "metadatas", "distances"]
            )
            parsed = self._parse_results(results, "milestone")
            logger.info("关系层检索: user=%s role=%s top_k=%d 命中=%d",
                        user_id, role_type, top_k, len(parsed))
            if parsed:
                for i, p in enumerate(parsed):
                    logger.info("  里程碑[%d] sim=%.4f text=%s", i, p["similarity"], p["text"][:80])
            return parsed
        except Exception as e:
            logger.error("retrieve_milestones 失败: %s", e)
            return []

    def retrieve_all_layers(self, user_id: str, role_type: str,
                            query: str) -> Dict[str, List[Dict]]:
        """
        三层联合检索：对同一查询向量，分别从三个集合检索。
        返回按层组织的结构化结果，供 Agent 分别消费。
        """
        logger.info("三层向量检索开始(全量): user=%s role=%s query=%s", user_id, role_type, query[:80])
        embedding = self._compute_embedding(query)
        if embedding is None:
            logger.error("retrieve_all_layers 终止: 嵌入计算失败")
            return {"facts": [], "emotions": [], "milestones": []}
        result = {
            "facts": self.retrieve_facts(user_id, role_type, embedding),
            "emotions": self.retrieve_emotions(user_id, role_type, embedding),
            "milestones": self.retrieve_milestones(user_id, role_type, embedding),
        }
        total = sum(len(v) for v in result.values())
        logger.info("三层向量检索完成: 总命中=%d (事实=%d 情感=%d 里程碑=%d)",
                    total, len(result["facts"]), len(result["emotions"]), len(result["milestones"]))
        return result

    # ------------- 商用级参数 -------------
    SIMILARITY_FLOOR = 0.30  # 相似度下限（低于此值的结果丢弃）

    # 嵌入 API 客户端：重试1次(8s→12s)，退避2s±25%，连续失败3次熔断2分钟
    _embed_client = ExternalAPIClient(
        name="embed-api",
        max_retries=1,
        timeouts=(8.0, 12.0),
        backoff_base=2.0,
        backoff_multiplier=1.5,
        backoff_jitter=0.25,
        circuit_threshold=3,
        circuit_cooldown=120.0,
    )

    def _compute_embedding(self, query: str) -> Optional[List[float]]:
        """计算查询向量，含重试+熔断。失败返回 None 由调用方降级。"""
        return self._embed_client.call(self.embeddings.embed_query, query)

    def _filter_by_similarity(self, results: List[Dict],
                              floor: float = None) -> List[Dict]:
        """过滤低相似度结果（噪音），保留 similarity >= floor 的条目。"""
        if floor is None:
            floor = self.SIMILARITY_FLOOR
        before = len(results)
        filtered = [r for r in results if r.get("similarity") is not None and r["similarity"] >= floor]
        if before > len(filtered):
            logger.info("相似度过滤: %d→%d (floor=%.2f)", before, len(filtered), floor)
        return filtered

    def smart_retrieve(self, user_id: str, role_type: str,
                       query: str, conversation_rounds: int = 0) -> Dict[str, List[Dict]]:
        """
        商用级智能路由检索 —— 唯一对外检索入口。

        管线:
        1. 计算查询嵌入向量（超时保护）
        2. 路由决策：规则路由 + LLM 兜底 → 激活层列表
        3. 按激活层分别检索 Chroma（各层独立查询）
        4. 相似度过滤：丢弃 similarity < 0.30 的噪音结果
        5. 返回按层组织的结构化结果

        降级策略:
        - 嵌入 API 挂 → 返回空结果（不阻塞对话）
        - 单层检索异常 → 该层返回空列表，其他层继续
        - 全链路超时(20s) → 返回已完成部分

        :param user_id:   用户ID
        :param role_type: 角色类型
        :param query:     用户当前消息
        :param conversation_rounds: 会话轮数（0=未知，影响路由决策）
        :return: {"facts": [...], "emotions": [...], "milestones": [...]}
        """
        t_start = _time.monotonic()

        result: Dict[str, List[Dict]] = {"facts": [], "emotions": [], "milestones": []}

        # ---------- 阶段1: 嵌入 ----------
        embedding = self._compute_embedding(query)
        # logger.info(f"嵌入计算完成: {embedding}")
        if embedding is None:
            logger.error("smart_retrieve 终止: 嵌入计算失败")
            return result

        embedding_ms = (_time.monotonic() - t_start) * 1000

        # ---------- 阶段2: 路由 ----------
        active_layers = self._router.decide(query, embedding, conversation_rounds)

        # ---------- 阶段3: 按激活层检索 ----------
        # 直接调用避免 lambda 开销；每个检索方法有自己的 try/except
        layer_handlers = {
            "facts": self.retrieve_facts,
            "emotions": self.retrieve_emotions,
            "milestones": self.retrieve_milestones,
        }

        for layer in active_layers:
            handler = layer_handlers.get(layer)
            if handler is None:
                continue
            try:
                raw = handler(user_id, role_type, embedding)
                result[layer] = self._filter_by_similarity(raw)
            except Exception as e:
                logger.error("smart_retrieve 层[%s]检索异常: %s", layer, e)
                # 该层失败不影响其他层

        # ---------- 阶段4: 汇总 ----------
        total_ms = (_time.monotonic() - t_start) * 1000
        counts = {k: len(v) for k, v in result.items()}
        total_hits = sum(counts.values())
        saved_layers = 3 - len(active_layers)

        logger.info(
            "smart_retrieve 完成: layers=%s saved=%d hits=%s total=%d "
            "embed=%.0fms total=%.0fms rounds=%d query='%s'",
            active_layers, saved_layers, counts, total_hits,
            embedding_ms, total_ms, conversation_rounds, query[:50]
        )
        return result

    @staticmethod
    def _parse_results(results, layer: str) -> List[Dict]:
        """将 Chroma 查询结果解析为统一的 dict 列表"""
        docs = results.get("documents")
        metas = results.get("metadatas")
        distances = results.get("distances")
        if not docs or not docs[0]:
            return []
        parsed = []
        for doc, meta, dist in zip(docs[0], metas[0], distances[0] if distances else [None] * len(docs[0])):
            parsed.append({
                "layer": layer,
                "text": doc,
                "similarity": round(1.0 - dist, 4) if dist is not None else None,
                "metadata": meta,
            })
        return parsed

    @staticmethod
    def format_layers_for_prompt(layers: Dict[str, List[Dict]]) -> str:
        """
        将三层检索结果格式化为 LLM prompt 可用文本。
        按层分组，方便 LLM 理解不同层级的记忆。
        """
        parts = []

        facts = layers.get("facts", [])
        if facts:
            lines = [f"  - {f['text']}" for f in facts]
            parts.append("[事实层] 关于用户的事实：\n" + "\n".join(lines))

        emotions = layers.get("emotions", [])
        if emotions:
            lines = [f"  - {e['text']}" for e in emotions]
            parts.append("[情感层] 相关情感记忆：\n" + "\n".join(lines))

        milestones = layers.get("milestones", [])
        if milestones:
            lines = [f"  - {m['text']}" for m in milestones]
            parts.append("[关系层] 相关关系里程碑：\n" + "\n".join(lines))

        return "\n\n".join(parts) if parts else ""
