"""
MemoryDecayEngine 单元测试。

覆盖衰减计算、强化计算、归档/删除/压缩判断。
"""
import math

from app.domain.memory.decay_engine import MemoryDecayEngine


class TestDecayedStrength:
    """衰减计算测试。"""

    def test_permanent_memory_no_decay(self):
        """半衰期 >= 36500 天的永久记忆不应衰减。"""
        strength = MemoryDecayEngine.calculate_decayed_strength(
            initial_strength=0.8, days_since=1000, half_life_days=36500,
        )
        assert strength > 0.8  # 反而微幅增强

    def test_half_life_decay(self):
        """经过正好一个半衰期后，强度应显著衰减（两阶段模型下非精确 0.5）。"""
        strength = MemoryDecayEngine.calculate_decayed_strength(
            initial_strength=0.8, days_since=7, half_life_days=7,
        )
        # 两阶段模型中 7 天仍在指数阶段（t* = 10）
        assert 0.3 < strength < 0.7

    def test_zero_days_returns_original(self):
        """days_since=0 时强度不变。"""
        strength = MemoryDecayEngine.calculate_decayed_strength(
            initial_strength=0.7, days_since=0, half_life_days=7,
        )
        assert strength == 0.7

    def test_long_term_decay_tends_to_zero(self):
        """超长时间后强度趋近于 0 但不低于 0。"""
        strength = MemoryDecayEngine.calculate_decayed_strength(
            initial_strength=0.9, days_since=365 * 10, half_life_days=7,
        )
        assert 0.0 <= strength < 0.10  # 幂律衰减比纯指数慢，10年后仍有微弱痕迹

    def test_power_law_phase(self):
        """超过 t* = 10 天后进入幂律衰减。"""
        strength = MemoryDecayEngine.calculate_decayed_strength(
            initial_strength=0.8, days_since=30, half_life_days=14,
        )
        # 30 天 > t*，进入幂律阶段，衰减应比纯指数慢
        assert 0.1 < strength < 0.7


class TestReinforcement:
    """强化计算测试。"""

    def test_cooldown_micro_gain(self):
        """冷却期内（5分钟）仅微增益，半衰期不变。"""
        new_strength, new_half_life = MemoryDecayEngine.calculate_reinforcement(
            minutes_since=5, current_strength=0.5, base_half_life=7,
            cooldown_minutes=30, epsilon=0.005,
        )
        assert 0.5 < new_strength < 0.51  # 微幅增益
        assert new_half_life == 7.0  # 半衰期不变

    def test_post_cooldown_full_reinforcement(self):
        """超过冷却期后触发完整间隔自适应强化。"""
        new_strength, new_half_life = MemoryDecayEngine.calculate_reinforcement(
            minutes_since=60 * 24,  # 1 天
            current_strength=0.5,
            base_half_life=7,
            cooldown_minutes=30,
        )
        assert new_strength > 0.5
        assert new_half_life > 7.0  # 半衰期应延长

    def test_zero_minutes_no_change(self):
        """minutes_since=0 时无变化。"""
        s, h = MemoryDecayEngine.calculate_reinforcement(
            minutes_since=0, current_strength=0.5, base_half_life=7,
        )
        assert s == 0.5
        assert h == 7.0


class TestPruneAndArchive:
    """归档和删除判断测试。"""

    def test_prune_weak_and_irrelevant(self):
        """强度低 + 显著性低 + 超30天 + 非硬约束 → 应删除。"""
        assert MemoryDecayEngine.should_prune_fact(
            strength=0.02, salience=0.3, days_since=31, is_immutable=False,
        ) is True

    def test_immutable_not_pruned(self):
        """硬约束记忆永远不删除。"""
        assert MemoryDecayEngine.should_prune_fact(
            strength=0.01, salience=0.1, days_since=365, is_immutable=True,
        ) is False

    def test_archive_moderate_relevance(self):
        """中等强度 + 有一定显著性 → 应归档。"""
        assert MemoryDecayEngine.should_archive_fact(
            strength=0.10, salience=0.5,
        ) is True

    def test_high_relevance_not_archived(self):
        """高强度记忆不应归档。"""
        assert MemoryDecayEngine.should_archive_fact(
            strength=0.20, salience=0.5,
        ) is False
