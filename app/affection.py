"""
好感度服务
实现 AffectionManager 接口，基于 SQLite 持久化
"""
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Dict
from app.config import Settings
from app.interfaces import AffectionManager
from app.exceptions import AffectionUpdateError

logger = logging.getLogger(__name__)

class AffectionService(AffectionManager):
    """基于 SQLite 的好感度管理"""

    def __init__(self, settings: Settings):
        logger.info("初始化好感度服务，数据库=%s", settings.AFFECTION_DB_PATH)
        self.db_path = settings.AFFECTION_DB_PATH
        self.decay_per_day = settings.AFFECTION_DECAY_PER_DAY
        self.lock = threading.Lock()   # 保证线程安全
        self._init_db()
        logger.info("好感度服务初始化完成")

    def _init_db(self):
        """创建表结构（如果不存在）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS affection
                            (user_id TEXT, role_type TEXT,
                             intimacy REAL DEFAULT 10,
                             trust REAL DEFAULT 10,
                             fun REAL DEFAULT 10,
                             growth REAL DEFAULT 10,
                             last_interaction TEXT,
                             PRIMARY KEY (user_id, role_type))''')

    def get(self, user_id: str, role_type: str) -> Dict[str, float]:
        """获取好感度，不存在则返回默认值 10"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT intimacy, trust, fun, growth FROM affection WHERE user_id=? AND role_type=?",
                (user_id, role_type)
            ).fetchone()
        if row:
            return {"intimacy": row[0], "trust": row[1], "fun": row[2], "growth": row[3]}
        return {"intimacy": 10, "trust": 10, "fun": 10, "growth": 10}

    def update(self, user_id: str, role_type: str, delta: Dict[str, float]):
        """更新好感度，使用锁保证并发安全"""
        with self.lock:
            try:
                current = self.get(user_id, role_type)
                new_vals = {}
                for dim in ["intimacy", "trust", "fun", "growth"]:
                    new_vals[dim] = max(0, min(100, current[dim] + delta.get(dim, 0)))
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        '''INSERT OR REPLACE INTO affection
                           (user_id, role_type, intimacy, trust, fun, growth, last_interaction)
                           VALUES (?,?,?,?,?,?,?)''',
                        (user_id, role_type, new_vals["intimacy"], new_vals["trust"],
                         new_vals["fun"], new_vals["growth"], datetime.now().isoformat())
                    )
                logger.info("好感度更新: %s -> 亲密度%.0f 信任%.0f 趣味%.0f 成长%.0f",
                            role_type, new_vals["intimacy"], new_vals["trust"],
                            new_vals["fun"], new_vals["growth"])
            except Exception as e:
                logger.error("好感度更新失败: %s", e, exc_info=True)
                raise AffectionUpdateError(f"好感度更新失败: {e}")

    def calculate_delta(self, user_msg: str, ai_response: str, emotion: dict) -> Dict[str, float]:
        """根据对话质量和情绪计算好感度变化"""
        delta = {"intimacy": 0.5, "trust": 0.3, "fun": 0, "growth": 0}
        # 消息长度加成（代表投入度）
        if len(user_msg) > 50:
            delta["intimacy"] += 0.5
        if len(user_msg) > 100:
            delta["intimacy"] += 0.5
        # 情绪影响
        label = emotion.get("label")
        if label in ["joy", "love"]:
            delta["fun"] += 0.8
            delta["intimacy"] += 0.3
        elif label == "sadness":
            delta["trust"] += 0.8
            delta["intimacy"] += 0.5
        # 回复中共情关键词
        if any(w in ai_response for w in ["理解", "明白", "抱抱", "摸摸头", "别难过"]):
            delta["trust"] += 0.5
            delta["intimacy"] += 0.5
        logger.debug("本轮好感度变化: %s", delta)
        return delta

    def apply_decay(self):
        """对所有超过 1 天未交互的记录执行衰减"""
        threshold = (datetime.now() - timedelta(days=1)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            c = conn.execute(
                f"UPDATE affection SET intimacy=MAX(0,intimacy-{self.decay_per_day}), "
                f"trust=MAX(0,trust-{self.decay_per_day}), fun=MAX(0,fun-{self.decay_per_day}), "
                f"growth=MAX(0,growth-{self.decay_per_day}) WHERE last_interaction < ?",
                (threshold,)
            )
        if c.rowcount:
            logger.info("好感度衰减完成，影响 %d 条记录", c.rowcount)

    def get_unlock_state(self, user_id: str, role_type: str) -> Dict:
        """根据平均好感度返回解锁等级和具体解锁项"""
        aff = self.get(user_id, role_type)
        avg = sum(aff.values()) / 4
        unlocks = {"level": 0, "style_modifier": "", "story_unlocked": False, "avatar_upgraded": False}
        if avg >= 30:
            unlocks["level"] = 1
            unlocks["style_modifier"] = "语气更亲密"
        if avg >= 50:
            unlocks["level"] = 2
            unlocks["style_modifier"] = "可以叫昵称，更随意"
        if avg >= 70:
            unlocks["level"] = 3
            unlocks["story_unlocked"] = True
        if avg >= 90:
            unlocks["level"] = 4
            unlocks["avatar_upgraded"] = True
        logger.debug("解锁状态查询: 平均好感%.1f, 等级%d", avg, unlocks["level"])
        return unlocks