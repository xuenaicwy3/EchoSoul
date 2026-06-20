import math
from datetime import datetime, timezone, timedelta


class MemoryDecayEngine:
    """
    艾宾浩斯遗忘曲线引擎
    核心公式：S(t) = S₀ × 2^(-t / T)

    该引擎负责管理用户记忆中各类事实（fact）、情感记录（emotion）、里程碑（milestone）的
    强度衰减、归档、压缩和删除策略。它模拟人类记忆的遗忘规律，同时结合显著性（salience）
    和来源（source）动态调整半衰期，实现智能化的长期记忆管理。


    基于认知神经科学共识的精确记忆强化引擎。
    基于艾宾浩斯遗忘曲线与突触可塑性理论的记忆衰减引擎

    理论基石：
    1. 多重记忆系统模型 (Atkinson-Shiffrin, 1968)：感觉记忆 → 工作记忆 → 长时记忆。
    2. 工作记忆理论 (Baddeley, 1974)：信息需成功进入长时巩固窗口才值得强化。
    3. 突触可塑性 (Kandel, 2000)：长时程增强(LTP)是记忆形成的细胞基础，早期巩固在刺激后立即开始。
    4. 间隔效应 (Ebbinghaus, 1885; Cepeda et al., 2006)：分散提取比集中重复更有效

    """
    # ---------- 科学共识参数 ----------
    ALPHA_TIME = 0.15          # 对数时间增益系数 (长期间隔强化)
    BETA_TIME = 0.4            # 双曲线时间增益系数 (短期提取努力)
    GAMMA_DIFFICULTY = 0.5     # 提取难度贡献系数 (Bjork, 1994 的努力假说)
    MAX_GAIN = 2.5             # 单次最大强化倍数 (避免强度爆炸)

    # 冷却期：15分钟（突触不应期的宏观窗口）
    # 科学依据：工作记忆的维持与早期长时巩固启动的分界点。
    # 在15分钟内，信息处于工作记忆复述或早期不稳定阶段，不应视为独立的提取事件。
    COOLDOWN_MINUTES = 15

    # ==================== 衰减计算 ====================
    @staticmethod
    def calculate_decayed_strength(initial_strength: float,
                           days_since: float,
                           half_life_days: int) -> float:
        """
        计算当前记忆强度（基于艾宾浩斯指数衰减模型）
        :param initial_strength: 初始强度或上次强化后的强度 (0~1)，即公式中的 S₀
        :param days_since: 距离 上次强化的时间，即公式中的 t
        :param half_life_days: 半衰期（天），即公式中的 T，表示强度衰减到一半所需的时间
        :return: 当前强度 (0~1)，即 S(t)

        公式：S(t) = S₀ × 2^(-t / T)
        指数底数为2，符合心理学中“记忆强度每过一个半衰期减半”的直观概念。
        """
        # 永久记忆处理：半衰期 >= 36500天（约100年）视为永久记忆，此时不仅不衰减，
        # 反而微幅增强（模拟“长久记忆会因反复提取而固化”的现象），但上限为1.0
        if half_life_days >= 36500:   # 永久记忆不衰减
            return min(1.0, initial_strength * 1.1)

        # 标准指数衰减计算：pow(2, -t/T) = 2^(-t/T)
        decayed = initial_strength * math.pow(2, -days_since / half_life_days)

        # 结果截断在 [0.0, 1.0] 范围内，防止浮点误差或异常值
        return max(0.0, min(1.0, decayed))


    @staticmethod
    def calculate_reinforcement(minutes_since: float, current_strength: float,
                                base_half_life: int,
                                cooldown_minutes: int = None,
                                epsilon: float = 0.005
                                ) -> tuple:
        """
        强化计算：冷却期内使用微增益策略，冷却期外使用完整的间隔自适应强化。
        返回值: (new_strength, new_half_life)

        :param minutes_since: 距上次真正强化的间隔 (分钟)
        :param current_strength: 当前记忆强度 (0~1)
        :param base_half_life: 当前半衰期 (天)
        :param cooldown_minutes: 冷却期（分钟），默认为 MemoryDecayEngine.COOLDOWN_MINUTES (15分钟)
        :param epsilon: 冷却期微增益系数，默认 0.005（事实/关系层），情感层可设为 0.01
        :return: (new_strength, new_half_life)
        """

        if cooldown_minutes is None:
            cooldown_minutes = MemoryDecayEngine.COOLDOWN_MINUTES

        # ---------- 1. 冷却期微增益策略 ----------
        if minutes_since < cooldown_minutes:
            # 增益 = 1 + ε / (Δt + 1)，其中ε = 0.005
            # 增益随间隔增大而迅速递减，模拟突触响应性下降
            micro_gain = 1.0 + epsilon / (minutes_since + 1.0)
            new_strength = min(1.0, current_strength * micro_gain)
            # 冷却期内半衰期不变
            return new_strength, base_half_life

        # ---------- 1. 冷却期保护 ----------
        # # 15分钟内的再次提及，属于工作记忆复述或早期不稳定巩固，不累加强化。
        # if not MemoryDecayEngine.should_reinforce(minutes_since):
        #     return current_strength, base_half_life

        # ---------- 2. 提取努力度计算 (基于艾宾浩斯数据) ----------
        # 艾宾浩斯(1885)实验数据记录了不同间隔后的遗忘量：
        #  20分钟: 41.8% 遗忘  → 提取努力度 0.42
        #  1小时:  55.8% 遗忘  → 提取努力度 0.56
        #  8.8小时:64.2% 遗忘  → 提取努力度 0.64
        #  24小时: 66.3% 遗忘  → 提取努力度 0.66
        #  31天:   78.9% 遗忘  → 提取努力度 0.79
        # 我们使用一个复合函数来拟合这条曲线：
        #  - 对数部分模拟长期平缓衰减 (1天至数年)
        #  - 双曲线部分模拟初期急剧衰减 (分钟至小时级)

        # ---------- 2. 间隔自适应强化 ----------
        dt = max(0.0, minutes_since / 1440.0)  # 转换为天
        # days = minutes_since / 1440.0

        # 长期平稳增益 (对数)
        time_gain_log = MemoryDecayEngine.ALPHA_TIME * math.log1p(dt)

        # 初期急剧增益 (双曲线，半饱和点约在1小时)
        time_gain_hyper = MemoryDecayEngine.BETA_TIME * (minutes_since / (minutes_since + 60.0))

        # 总时间增益 = 对数 + 双曲线，完美拟合艾宾浩斯遗忘曲线
        time_gain = time_gain_log + time_gain_hyper

        # ---------- 3. 提取难度贡献 (提取努力假说) ----------
        # 认知心理学经典发现：提取越困难，成功后的巩固越强 (Bjork, 1994)。
        # 当前强度越低，说明衰减越严重，提取所需的认知努力就越大。
        # 使用 (1-S)^2 是为了放大低强度记忆的巩固效果，帮助其快速恢复。
        difficulty_gain = MemoryDecayEngine.GAMMA_DIFFICULTY * (1.0 - current_strength) ** 2

        # ---------- 4. 睡眠巩固加成 ----------
        # 睡眠依赖的记忆巩固 (Stickgold, 2005)：
        # 如果提取发生在学习后的第一个夜晚之后（>12小时），记忆已得到睡眠的初步整理，
        # 此时的成功提取意味着记忆更稳固，应给予微小加成。
        sleep_bonus = 0.0
        if minutes_since > 720:  # 超过12小时，可能经历了一次睡眠
            sleep_bonus = 0.05

        # ---------- 5. 总强化倍数 ----------
        multiplier = 1.0 + time_gain + difficulty_gain + sleep_bonus
        multiplier = min(multiplier, MemoryDecayEngine.MAX_GAIN)

        # ---------- 6. 新强度 ----------
        new_strength = min(1.0, current_strength * multiplier)

        # ---------- 7. 半衰期更新 ----------
        # 半衰期延长幅度为强度增幅的80%。
        # 科学依据：提取后的记忆衰退速度会变慢，但半衰期的增长不应快于强度的增长。
        half_life_mult = 1.0 + 0.8 * max(0, (multiplier - 1.0))
        new_half_life = min(36500, int(base_half_life * half_life_mult))

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
        return strength < 0.05 and salience < 0.4 and days_since > 30

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


