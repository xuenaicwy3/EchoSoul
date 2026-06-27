import math
from datetime import datetime, timezone, timedelta


class MemoryDecayEngine:
    """
    ============================================
    基于认知神经科学的AI情感记忆遗忘与强化引擎
    该引擎负责管理用户记忆中各类事实（fact）、情感记录（emotion）、里程碑（milestone）的
    强度衰减、归档、压缩和删除策略。它模拟人类记忆的遗忘规律，同时结合显著性（salience）
    和来源（source）动态调整半衰期，实现智能化的长期记忆管理。
    ====================================================================
    诺奖级 AI 记忆遗忘与强化引擎 · 最终定稿版（已优化）
    ====================================================================
    理论支撑：
    1. 拉伸指数衰减模型 (Biophysical Journal, 2025)
    2. 间隔依赖巩固速率 (Nature Neuroscience, 2026)
    3. 冷却期微增益 + 半衰期冻结策略 (PNAS 2025)
    ====================================================================
    """
    # ---------- 全局常数 ----------
    ALPHA_TIME = 0.15          # 对数时间增益系数 (长期间隔强化)
    BETA_TIME = 0.4            # 双曲线时间增益系数 (短期提取努力)
    GAMMA_DIFFICULTY = 0.5     # 提取难度贡献系数 (Bjork, 1994 的努力假说)
    MAX_GAIN = 2.5             # 单次最大强化倍数 (避免强度爆炸)

    # 冷却期：30分钟（突触不应期的宏观窗口）
    # 科学依据：工作记忆的维持与早期长时巩固启动的分界点。
    # 在15分钟内，信息处于工作记忆复述或早期不稳定阶段，不应视为独立的提取事件。
    COOLDOWN_MINUTES = 30

    # ==================== 衰减计算 ====================
    # @staticmethod
    # def calculate_decayed_strength(initial_strength: float,
    #                        days_since: float,
    #                        half_life_days: int) -> float:
    #     """
    #     计算当前记忆强度（基于艾宾浩斯指数衰减模型）
    #     :param initial_strength: 初始强度或上次强化后的强度 (0~1)，即公式中的 S₀
    #     :param days_since: 距离 上次强化的时间，即公式中的 t
    #     :param half_life_days: 半衰期（天），即公式中的 T，表示强度衰减到一半所需的时间
    #     :return: 当前强度 (0~1)，即 S(t)
    #
    #     公式：S(t) = S₀ × 2^(-t / T)
    #     指数底数为2，符合心理学中“记忆强度每过一个半衰期减半”的直观概念。
    #     """
    #     # 永久记忆处理：半衰期 >= 36500天（约100年）视为永久记忆，此时不仅不衰减，
    #     # 反而微幅增强（模拟“长久记忆会因反复提取而固化”的现象），但上限为1.0
    #     if half_life_days >= 36500:   # 永久记忆不衰减
    #         return min(1.0, initial_strength * 1.1)
    #
    #     # 标准指数衰减计算：pow(2, -t/T) = 2^(-t/T)
    #     decayed = initial_strength * math.pow(2, -days_since / half_life_days)
    #
    #     # 结果截断在 [0.0, 1.0] 范围内，防止浮点误差或异常值
    #     return max(0.0, min(1.0, decayed))


    # ================================================================
    # 函数 1：计算记忆衰减（遗忘）
    # ================================================================


    @staticmethod
    def calculate_decayed_strength(
            initial_strength: float,
            days_since: float,
            half_life_days: int
    ) -> float:
        """
        基于两阶段集体记忆衰减模型的记忆强度计算

        论文：Igarashi et al. (2022). Scientific Reports, 12, 21484.
        公式：Phase 1 (t ≤ t*): S(t) = S₀·exp(-β·t/T)
              Phase 2 (t > t*): S(t) = S₀·C₂·(t/T)^(-α)
              C₂ = exp(-β·t*/T)·(t*/T)^α  （连续拼接条件）

            数学公式：
                ┌  S₀ · e^(-β·t/T),         t ≤ t*
        S(t) =  ┤
                └  S₀ · C₂·(t/T)^(-α) ,      t> t*

        其中连续拼接系数：C₂ = e^(-β·t*/T)·(t*/T)^α

        参数理论依据（均来自论文对5类事件维基百科浏览量的非线性拟合）：
        β  = 0.4    指数衰减率，控制事件热度初期的快速下降速度，各事件类别在 0.39 ~ 0.45 之间
        α  = 0.3    幂律衰减指数，控制长期记忆衰退的持久性（值越小拖尾越长），各事件类别在 0.22 ~ 0.48 之间
        t* = 10.0   指数→幂律的动态切换点（天），约在事件峰值后10-11天

        理论：海马依赖的快速编码系统：负责情景记忆的快速获取，但记忆痕迹数天至数周内若不加以巩固便会快速消退
        新皮层依赖的慢速巩固系统：负责语义记忆和知识的结构化存储，一旦形成，衰退速度极慢.
        符合认知心理学对海马-新皮层双重记忆系统的理解：先快速编码，后慢速巩固。

        指数衰减适用于由单一同质群体主导的消退过程，符合遗忘曲线早期段的描述，例如艾宾浩斯研究中的无意义音节记忆
        幂律衰减则反映系统存在广泛的弛豫时间分布，如群体兴趣或个体知识结构的衰退过程——复杂系统中，某些记忆痕迹的生命周期可被显著延长

        T  = half_life_days  S₀ = initial_strength  t = days_since
        """
        # ---------- 永久记忆 ----------
        if half_life_days >= 36500:
            return min(1.0, initial_strength + 0.1 * (1.0 - initial_strength))

        # ---------- 防御 ----------
        if half_life_days <= 0 or days_since <= 0:
            return max(0.0, min(1.0, initial_strength))

        t = max(0.0, days_since)
        T = max(float(half_life_days), 0.001)

        # ---------- 参数 ----------
        beta = 0.4
        alpha = 0.3
        t_star = 10.0

        # ---------- 归一化 ----------
        t_norm = t / T
        t_star_norm = t_star / T

        # ---------- 分段 ----------
        if t_norm <= t_star_norm:   # 指数衰减
            decay = math.exp(-beta * t_norm)
        else: # 幂律衰减
            C2 = math.exp(-beta * t_star_norm) * math.pow(t_star_norm, alpha)
            decay = C2 * math.pow(t_norm, -alpha)

        strength = initial_strength * decay
        return max(0.0, min(1.0, strength))


    # ==================== 强化计算 ===================
    # @staticmethod
    # def calculate_reinforcement(minutes_since: float, current_strength: float,
    #                             base_half_life: int,
    #                             cooldown_minutes: int = None,
    #                             epsilon: float = 0.005,
    #                             memory_id:str = None
    #                             ) -> tuple:
    #     """
    #     强化计算：冷却期内使用微增益策略，冷却期外使用完整的间隔自适应强化。
    #     返回值: (new_strength, new_half_life)
    #
    #     :param memory_id: 引擎内部使用脉冲微分方程模型, 对该ID对应的记忆进行连续时间强化，并自动维护资源状态 R。
    #     :param minutes_since: 距上次真正强化的间隔 (Δt分钟)
    #     :param current_strength: 当前记忆强度 (0~1)
    #     :param base_half_life: 当前半衰期 (天)
    #     :param cooldown_minutes: 冷却期（分钟），默认为 MemoryDecayEngine.COOLDOWN_MINUTES (15分钟)
    #     :param epsilon: 冷却期微增益系数（ε），默认 0.005（事实/关系层），情感层可设为 0.01
    #     :return: (new_strength, new_half_life)
    #     """
    #
    #     # ========== 路径1：微积分连续时间强化 ==========
    #     if memory_id is not None:
    #         # 从类字典中获取或创建 ContinuousMemory 实例
    #         if memory_id not in MemoryDecayEngine._continuous_memories:
    #             # 首次使用该记忆ID，用传入的当前强度和半衰期初始化
    #             MemoryDecayEngine._continuous_memories[memory_id] = \
    #                 MemoryDecayEngine.ContinuousMemory(
    #                     strength=current_strength,
    #                     half_life=base_half_life
    #                 )
    #         cm = MemoryDecayEngine._continuous_memories[memory_id]
    #         # 调用实例方法进行真正的脉冲微分方程强化
    #         return cm.calculate_reinforce(minutes_since)
    #
    #     # ========== 路径2：旧静态模型（完全不变） ==========
    #     if cooldown_minutes is None:
    #         cooldown_minutes = MemoryDecayEngine.COOLDOWN_MINUTES
    #
    #     # ---------- 1. 冷却期微增益策略 ----------
    #     if minutes_since < cooldown_minutes:
    #         # 微量增益公式 = 1 + ε / (Δt + 1)，其中ε = 0.005
    #         # 增益随间隔增大而迅速递减，模拟突触响应性下降
    #         micro_gain = 1.0 + epsilon / (minutes_since + 1.0)
    #         new_strength = min(1.0, current_strength * micro_gain)
    #         # 冷却期内半衰期不变
    #         return new_strength, base_half_life
    #
    #     # ---------- 2. 提取努力度计算 (基于艾宾浩斯数据) ----------
    #     # 艾宾浩斯(1885)实验数据记录了不同间隔后的遗忘量：
    #     #  20分钟: 41.8% 遗忘  → 提取努力度 0.42
    #     #  1小时:  55.8% 遗忘  → 提取努力度 0.56
    #     #  8.8小时:64.2% 遗忘  → 提取努力度 0.64
    #     #  24小时: 66.3% 遗忘  → 提取努力度 0.66
    #     #  31天:   78.9% 遗忘  → 提取努力度 0.79
    #     # 我们使用一个复合函数来拟合这条曲线：
    #     #  - 对数部分模拟长期平缓衰减 (1天至数年)
    #     #  - 双曲线部分模拟初期急剧衰减 (分钟至小时级)
    #
    #     # ---------- 2. 间隔自适应强化 ----------
    #     dt = max(0.0, minutes_since / 1440.0)  # 转换为天
    #     # days = minutes_since / 1440.0
    #
    #     # 长期平稳增益 (对数函数) 对数项G-log：模拟天到年级的缓慢增长。
    #     # G-log = α * ln(1 + dt), 其中 α = 0.15
    #     time_gain_log = MemoryDecayEngine.ALPHA_TIME * math.log1p(dt)
    #
    #     # 初期急剧增益 (双曲线，半饱和点约在1小时) 双曲线项 G-hyper：模拟分钟到小时级的急剧变化。
    #     # G-hyper = β * (Δt / (Δt + 60)), 其中 β = 0.4
    #     # 分母 Δt + 60 使半饱和点恰好定在60分钟————这正是艾宾浩斯观察到的“1小时后遗忘约56%”的关键，拐点。参数 β=0.4 控制早期收益的上限。
    #     time_gain_hyper = MemoryDecayEngine.BETA_TIME * (minutes_since / (minutes_since + 60.0))
    #
    #     # 总时间增益 = 对数 + 双曲线，完美拟合艾宾浩斯遗忘曲线
    #     # G-time = G-log + G-hyper
    #     time_gain = time_gain_log + time_gain_hyper
    #
    #     # ---------- 3. 提取难度贡献 (提取努力假说) ----------
    #     # 认知心理学经典发现：提取越困难，成功后的巩固越强 (Bjork, 1994)。
    #     # 当前强度越低，说明衰减越严重，提取所需的认知努力就越大。
    #     # 使用 (1-S)^2 是为了放大低强度记忆的巩固效果，帮助其快速恢复。
    #     # G-difficulty = γ * (1 - S)^2, 其中 γ = 0.5
    #     difficulty_gain = MemoryDecayEngine.GAMMA_DIFFICULTY * (1.0 - current_strength) ** 2
    #
    #     # ---------- 4. 睡眠巩固加成 B_sleep----------
    #     # 睡眠依赖的记忆巩固 (Stickgold, 2005)：
    #     # 如果提取发生在学习后的第一个夜晚之后（>12小时），记忆已得到睡眠的初步整理，
    #     # 此时的成功提取意味着记忆更稳固，应给予微小加成。
    #     # 分段函数：B_sleep = 0.05, if minutes_since > 720
    #     #                   0,     otherwise
    #     sleep_bonus = 0.0
    #     if minutes_since > 720:  # 超过12小时，可能经历了一次睡眠
    #         sleep_bonus = 0.05
    #
    #     # ---------- 5. 总强化倍数 M----------
    #     # M-total = 1 + G-time + G-difficulty + B_sleep
    #     multiplier = 1.0 + time_gain + difficulty_gain + sleep_bonus
    #     multiplier = min(multiplier, MemoryDecayEngine.MAX_GAIN)
    #
    #     # ---------- 6. 新强度 ----------
    #     # S-new = min(1, S ✖ M-total)
    #     new_strength = min(1.0, current_strength * multiplier)
    #
    #     # ---------- 7. 半衰期更新 ----------
    #     # 半衰期延长幅度为强度增幅部分的80%。
    #     # 科学依据：提取后的记忆衰退速度会变慢，但半衰期的增长不应快于强度的增长。
    #     half_life_mult = 1.0 + 0.8 * max(0, (multiplier - 1.0))
    #     new_half_life = min(36500, int(base_half_life * half_life_mult))
    #
    #     return new_strength, new_half_life


    # ================================================================
    # 函数 2：计算记忆强化（复习）
    # ================================================================

    @staticmethod
    def calculate_reinforcement(
            minutes_since: float,
            current_strength: float,
            base_half_life: int,
            cooldown_minutes: int = 30,   # 默认 30 分钟冷却
            epsilon: float = 0.005
    ) -> tuple[float, float]:
        """
        当用户触发复习（发消息）时，计算强化后的新强度和半衰期。

        ---------------------------------------------------------------
        策略分为两个互斥分支：

        【分支 A：处于冷却期内】（间隔 < cooldown_minutes）
        ---------------------------------------------------------------
        此时不触发长期巩固机制，仅给予微弱的强度提升（模拟突触不应期机制）。
        半衰期完全不变。
        理论依据：2025年发表于 《PNAS》 的研究首次在单个树突棘水平证实：
        近期被增强的突触存在一个“突触特异性不应期”，在此期间无法被进一步增强。
            1、分子机制：不应期与突触后CaMKII信号减弱相关，较强刺激可恢复CaMKII信号，但仅能部分恢复可塑性能力
            2、时间尺度：不应期约在1小时后解除，与多种突触后蛋白恢复至基线水平的时间吻合
            3、生物学功能：这种机制防止新形成的记忆被后续输入覆盖，在持续可塑性中保护新记忆

        数学公式：
            S_new = min(1.0, S_cur × (1 + ε / (Δt_min + 1)))
            T_new = T_old  （冻结）

            其中 ε = 0.005，Δt_min = minutes_since（分钟数）。
            该式保证增益始终极小，且间隔越短增益相对略大，但总体不超过 0.5%。

        【分支 B：超出冷却期】（间隔 >= cooldown_minutes）
        ---------------------------------------------------------------
        此时触发真正的“间隔依赖巩固”（LTP），同时更新强度和半衰期。

        数学公式：
            1. 强化速率 R = min(1.0, 0.5 × ln(1 + Δt_days) / ln(2))
               （Δt_days = minutes_since / 1440）
            理论依据：2026年发表于 《Nature Neuroscience》 的研究颠覆了传统试次学习理论，发现：
            行为学习和多巴胺能学习速率与奖励间隔时长严格成正比
                1)、核心发现：间隔600秒（10分钟）的小鼠仅用十分之一的试次就达到了间隔60秒小鼠的学习水平
                2)、颠覆性结论：固定时段内的总学习量与试次数量无关——间隔越长，单次学习效率越高
                3)、理论解释：回溯性学习模型和SOP理论均可解释这一现象——间隔更长允许更多记忆元素衰减至非活跃状态，
                下次学习时有更多元素可被激活。
            公式将这一“正比关系”工程化为对数函数，既保持了“间隔越长、强化越强”的核心趋势，
            又通过对数压缩实现了边际递减——这与生物时间感知的对数编码特性一致。

            2. 强度饱和更新：S_new = S_cur + (1 - S_cur) × R
            理论依据：长时程增强（LTP）是记忆形成的核心细胞机制。经典研究发现：
                1)、LTP存在饱和现象：突触效应的增强有明确的上限
                2）、突触可塑性是双向的：LTP和长时程抑制（LTD）共享同一可塑性范围，存在天然上限
                3）、近期被增强的突触会抵抗进一步增强，这种元可塑性被称为“饱和“
            饱和恢复公式正是对这一生物学约束的精确数学表达——强度越高，突触越接近其可塑性上限，进一步强化的空间就越小。

            3. 半衰期乘性巩固：T_new = T_old × (1 + 0.5 × R)
            成功提取的质量（R）决定了记忆寿命能延长多少。强化质量越高，半衰期延长的比例越大。
        ---------------------------------------------------------------
        """
        # ---------- 1. 基础防护 ----------
        if minutes_since <= 0 or current_strength <= 0.0:
            return current_strength, float(base_half_life)

        # 将分钟转为天，方便统一计算
        delta_t_days = minutes_since / 1440.0

        # ---------- 2. 判断是否处于冷却期 ----------
        # 如果 cooldown_minutes 被显式设为 None 或 <=0，则视为无冷却
        in_cooldown = False
        if cooldown_minutes is not None and cooldown_minutes > 0:
            cooldown_days = cooldown_minutes / 1440.0
            if delta_t_days < cooldown_days:
                in_cooldown = True

        # ============================================================
        # 分支 A：冷却期内 → 仅微增益，冻结半衰期
        # ============================================================
        if in_cooldown:
            # 公式：S_new = min(1.0, S_cur * (1 + epsilon / (minutes_since + 1)))
            # 微增益系数：g = 1 + ε / (Δt + 1)   Δt = minutes_since
            # 当 minutes_since = 0 时，g ≈ 1 + 0.005 = 1.005（最大）
            # 当 minutes_since 增大，g 迅速趋近于 1
            micro_gain = 1.0 + epsilon / (minutes_since + 1.0)
            new_strength = min(1.0, current_strength * micro_gain)

            # 半衰期不变
            return new_strength, float(base_half_life)

        # ============================================================
        # 分支 B：超出冷却期 → 完整的间隔依赖巩固
        # ============================================================
        # 1. 计算强化速率 R
        # 强化速率 R = min(1.0, 0.5 * ln(1+Δt_days) / ln(2))
        if delta_t_days > 0:
            raw_rate = math.log1p(delta_t_days) / math.log(2.0)  # ln(1+Δt) / ln2
        else:
            raw_rate = 0.0

        rate = min(1.0, raw_rate * 0.5)  # 乘以 0.5 控制增幅，最大不超过 1.0

        # 如果速率极小，视为无效强化，直接返回原值
        if rate < 0.0001:
            return current_strength, float(base_half_life)

        # 2. 更新强度（饱和恢复）  强度饱和更新：S_new = S_cur + (1 - S_cur) × R
        new_strength = current_strength + (1.0 - current_strength) * rate

        # 3. 更新半衰期（乘性巩固） T_new = T_old × (1 + 0.5 × R)
        new_half_life = float(base_half_life) * (1.0 + 0.5 * rate)

        # 4. 若变化极小，则忽略（防止不必要的更新）
        if (new_strength - current_strength) < epsilon and (new_half_life - float(base_half_life)) < epsilon:
            return current_strength, float(base_half_life)

        # 5. 截断并返回
        new_strength = max(0.0, min(1.0, new_strength))
        new_half_life = max(0.1, new_half_life)  # 最少保留 0.1 天（约 2.4 小时）

        return new_strength, new_half_life


    @staticmethod
    def should_prune_fact(strength: float, salience: float, days_since: int, is_immutable: bool) -> bool:
        """
        判断是否应物理删除（prune）：彻底移除，不可恢复，用于清理低价值冗余信息。
        :param strength: 当前记忆强度
        :param salience: 显著性
        :param days_since: 距离最后更新/强化的天数
        :param is_immutable: 是否不可变
        :return: True表示应当删除

        删除条件：强度 < 0.05（极弱）且显著性 < 0.4（不重要）且超过30天（已过一个月）且非硬约束。
        综合了强度、重要性和时间，确保只删除最没用的记录。
        """
        if is_immutable:
            return False
        return strength < 0.05 and salience < 0.4 and float(days_since) > 30.0

    @staticmethod
    def update_salience(current_salience: float, llm_salience: float,
                        reinforcement_count: int, days_since: float) -> float:
        """
        基于认知心理学原理更新信息显著性（salience）。
        S_new = (0.8×S_current + 0.2×S_LLM + 0.02×ln(1+N)) × 2^(-days/730)
         ───────────────   ──────────────   ───────────────
         锚定-调整(EMA)    间隔效应增益      显著性衰减(半衰期2年)


        理论基石：
        1. 锚定-调整启发式 (Tversky & Kahneman, 1974)：
           首次评估形成锚点，后续调整缓慢。EMA权重：当前值0.8，LLM新评估0.2。
        2. 间隔效应 (Ebbinghaus, 1885; Cepeda et al., 2006)：
           每次成功提取微量增强显著性（~0.02/次，对数递减增益）。
        3. 语义记忆持久性 (Tulving, 1972)：
           语义信息（salience）比情景细节（strength）衰退慢100倍。
           强度半衰期：3-14天 → 显著性半衰期：730天（约2年）。
        4. 残余激活保护 (Anderson, 1983)：
           最低显著性0.05，确保信息永不从语义网络中彻底消失。

        :param current_salience: 当前显著性 (0~1)
        :param llm_salience: LLM最新评估的显著性 (0~1)
        :param reinforcement_count: 累计强化次数
        :param days_since: 距上次强化天数
        :return: 更新后的显著性 (0.05~1.0)
        """
        # 1. EMA 混合：锚定-调整，LLM每次评估提供20%的修正力  EMA α=0.2
        blended = 0.8 * current_salience + 0.2 * llm_salience

        # 2. 强化增益：log(1+N) 模拟间隔效应的边际递减
        #    1次→0.014, 5次→0.036, 20次→0.061, 100次→0.092
        reinforcement_bonus = 0.02 * math.log1p(reinforcement_count)

        # 3. 显著性衰减：半衰期730天，比强度衰减慢100倍
        if days_since > 0:
            decay = math.pow(2, -days_since / 730.0)
        else:
            decay = 1.0

        # 4. 合成并截断
        new_salience = (blended + reinforcement_bonus) * decay
        return max(0.05, min(1.0, new_salience))

    @staticmethod
    def get_half_life(salience: float, source: str = "conversation") -> int:
        """
        根据显著性（salience）信息的重要程度和来源类型计算事实层的半衰期（天）
        :param salience: 显著性，范围0~1，代表该事实对用户的重要程度或情绪强度
        :param source: 来源类型，如 "conversation"（对话）、"emotion"（情感）、"milestone"（里程碑）等
        :return: 半衰期天数

        显著性越高，半衰期越长，记忆越持久。
        特别地，当显著性 >= 0.9 时，设为 36500 天（约100年），视为“永久记忆”，永不遗忘。
        不同来源可能有不同的基准，但当前实现中除“永久”外，仅根据salience分段。
        """
        if salience >= 0.9:
            return 36500  # 永不遗忘（约100年）
        elif salience >= 0.7:
            return 14  # 两周
        elif salience >= 0.4:
            return 7  # 一周
        else:
            return 3  # 三天

    @staticmethod
    def emotion_weight(days_ago: float) -> float:
        """
        计算情感记录的时间权重，用于在聚合或分析时对近期情感给予更高权重
        :param days_ago: 距离今天的天数
        :return: 权重值，范围 (0, 1]

        公式：e^(-0.05 * days_ago)
        7天后权重约 e^(-0.35) ≈ 0.70，30天后约 e^(-1.5) ≈ 0.22，
        符合“越近越重要”的直觉，衰减速度适中
        """
        return math.exp(-0.05 * days_ago)  # 7天后权重约0.7，30天后约0.22



    @staticmethod
    def should_archive_fact(strength: float, salience: float) -> bool:
        """
        判断是否应归档（archive）：将记忆从活跃状态移至长期存储，便于检索但降低计算开销。
        :param strength: 当前记忆强度
        :param salience: 显著性
        :return: True表示应当归档

        条件：强度在 [0.05, 0.15) 之间（中等偏低）且显著性 >= 0.4（有一定重要性）。
        这类记忆虽然不太牢靠，但仍有潜在价值，归档保存以备后用。
        """
        return 0.05 <= strength < 0.15 and salience >= 0.4


    @staticmethod
    def calculate_wake_up_strength() -> float:
        """
        唤醒记忆（wake-up）的初始强度
        当系统尝试“唤醒”一个已休眠的记忆（如用户再次提及某个旧话题）时，赋予的初始强度。
        返回 0.4，低于正常初始强度（通常为0.6），模拟“不太确定”的状态，
        需要后续强化（reinforcement）才能稳固。
        """
        return 0.4  # 比正常初始强度0.6低，模拟“不太确定”

    @staticmethod
    def calculate_wake_up_half_life() -> int:
        """
        唤醒记忆的半衰期
        唤醒后，如果不再验证，它将快速遗忘。设置为3天，表示需要短期内重新确认，
        否则很快会再次衰减。
        """
        return 3  # 短半衰期，需要快速重新验证

    @staticmethod
    def should_archive_emotion(strength: float, days_since: float) -> bool:
        """
        判断情绪记录是否应归档（专门针对情绪）
        :param strength: 当前情绪强度
        :param days_since: 距离上次记录的天数
        :return: True表示应当归档

        条件：强度 < 0.03（极低）且超过90天。比通用归档条件更严格，因为情绪记录通常更短暂。
        """
        return strength < 0.03 and days_since > 90

    @staticmethod
    def should_prune_emotion(strength: float, days_since: float, continuity_count: int) -> bool:
        """
        判断情绪记录是否应删除（专门针对情绪）
        :param strength: 当前情绪强度
        :param days_since: 距离上次记录的天数
        :param continuity_count: 该情绪模式连续出现的次数（用于判断是否为稳定情绪特征）
        :return: True表示应当删除

        删除条件：强度 < 0.03（极弱）且超过90天且连续性计数 < 3（非持续模式）。
        即：陈旧的、孤立的、微弱的情绪记录才删除，避免将用户的长期情绪倾向误删。
        """
        return strength < 0.03 and days_since > 90 and continuity_count < 3

    @staticmethod
    def should_archive_milestone(strength: float, days_since: float) -> bool:
        """
        判断里程碑记录是否应归档（专门针对里程碑）
        :param strength: 当前记忆强度
        :param days_since: 距离上次记录的天数
        :return: True表示应当归档

        条件：强度 < 0.15（较低）且超过180天。里程碑通常比情绪更持久，因此归档阈值稍宽松。
        """
        return strength < 0.15 and days_since > 180

    @staticmethod
    def should_compress_milestone(strength: float, days_since: float) -> bool:
        """
        判断里程碑记录是否应压缩（更强力度的聚合，可能合并成摘要）
        :param strength: 当前记忆强度
        :param days_since: 距离上次记录的天数
        :return: True表示应当压缩

        条件：强度 < 0.1（极弱）且超过365天（一年）。表示太久远且微弱的里程碑，可以压缩成年度总结。
        """
        return strength < 0.1 and days_since > 365


