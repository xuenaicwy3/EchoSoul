from sqlalchemy import Column, Integer, String, Float, Text, DateTime, func, PrimaryKeyConstraint, Boolean, Date
from app.database import Base

class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role_type = Column(String(64), nullable=False, index=True)
    sender = Column(String(10), nullable=False)
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        PrimaryKeyConstraint("id", "role_type", name="pk_chat_history"),
    )

    def to_dict(self):
        return {
            "sender": self.sender,
            "message": self.message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }

class Affection(Base):
    __tablename__ = "affection"
    user_id = Column(String(64), primary_key=True)
    role_type = Column(String(64), primary_key=True)
    intimacy = Column(Float, default=10.0)
    trust = Column(Float, default=10.0)
    fun = Column(Float, default=10.0)
    growth = Column(Float, default=10.0)
    last_interaction = Column(DateTime(timezone=True), server_default=func.now())


# 每日任务定义表
class DailyTaskTemplate(Base):
    __tablename__ = "daily_task_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)          # 任务名称，如“早安问候”
    description = Column(String(255))                   # 任务描述
    reward_intimacy = Column(Float, default=5.0)        # 完成奖励亲密度
    key_trigger = Column(String(64))                    # 触发关键词（可选）

# 用户每日任务进度表
class UserDailyTask(Base):
    __tablename__ = "user_daily_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role_type = Column(String(64), nullable=False)
    task_template_id = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)                 # 任务所属日期
    completed = Column(Boolean, default=False)
    completion_time = Column(DateTime, nullable=True)

# 成就定义表
class Achievement(Base):
    __tablename__ = "achievements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)           # 成就名称
    description = Column(String(255))
    category = Column(String(32))                       # 如 "chat_count", "chat_length", "consecutive_days"
    threshold = Column(Integer)                         # 达成阈值
    reward_intimacy = Column(Float, default=10.0)

# 用户成就进度表
class UserAchievement(Base):
    __tablename__ = "user_achievements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    achievement_id = Column(Integer, nullable=False)
    progress = Column(Integer, default=0)               # 当前进度
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime, nullable=True)

# 皮肤/主题表
class Skin(Base):
    __tablename__ = "skins"
    id = Column(Integer, primary_key=True, autoincrement=True)
    role_type = Column(String(64), nullable=False)
    name = Column(String(64), nullable=False)
    description = Column(String(255))
    unlock_condition = Column(Text)                     # 解锁条件描述，如 "亲密度达到30"
    unlock_type = Column(String(32))                    # 条件类型: "intimacy", "achievement", "task"
    unlock_value = Column(Integer)                      # 条件阈值

# 用户皮肤表
class UserSkin(Base):
    __tablename__ = "user_skins"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role_type = Column(String(64), nullable=False)
    skin_id = Column(Integer, nullable=False)
    equipped = Column(Boolean, default=False)           # 是否当前使用