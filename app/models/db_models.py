from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, func, PrimaryKeyConstraint, Boolean, Date, text
from app.database import Base

# 北京时间时区对象
BEIJING_TZ = ZoneInfo("Asia/Shanghai")

class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role_type = Column(String(64), nullable=False, index=True)
    sender = Column(String(10), nullable=False)
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=text("(now() AT TIME ZONE 'utc')"), index=True)

    __table_args__ = (
        PrimaryKeyConstraint("id", "role_type", name="pk_chat_history"),
    )

    def to_dict(self):
        ts = self.timestamp
        timestamp_str = None
        if ts:
            # 如果数据库取出的 datetime 没有时区信息（naive），设定为 UTC
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            # 转换为北京时间
            ts_beijing = ts.astimezone(BEIJING_TZ)
            timestamp_str = ts_beijing.strftime('%Y-%m-%d %H:%M:%S')
        return {
            "sender": self.sender,
            "message": self.message,
            "timestamp": timestamp_str
        }


class Affection(Base):
    __tablename__ = "affection"
    user_id = Column(String(64), primary_key=True)
    role_type = Column(String(64), primary_key=True)
    intimacy = Column(Float, default=10.0)
    trust = Column(Float, default=10.0)
    fun = Column(Float, default=10.0)
    growth = Column(Float, default=10.0)
    last_interaction = Column(DateTime(timezone=True), server_default=text("(now() AT TIME ZONE 'utc')"))


# 每日任务定义表
class DailyTaskTemplate(Base):
    __tablename__ = "daily_task_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    description = Column(String(255))
    reward_intimacy = Column(Float, default=5.0)
    key_trigger = Column(String(64))

# 用户每日任务进度表
class UserDailyTask(Base):
    __tablename__ = "user_daily_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role_type = Column(String(64), nullable=False)
    task_template_id = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    completed = Column(Boolean, default=False)
    completion_time = Column(DateTime(timezone=True), nullable=True)

# 成就定义表
class Achievement(Base):
    __tablename__ = "achievements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    description = Column(String(255))
    category = Column(String(32))
    threshold = Column(Integer)
    reward_intimacy = Column(Float, default=10.0)

# 用户成就进度表
class UserAchievement(Base):
    __tablename__ = "user_achievements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    achievement_id = Column(Integer, nullable=False)
    progress = Column(Integer, default=0)
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

# 皮肤/主题表
class Skin(Base):
    __tablename__ = "skins"
    id = Column(Integer, primary_key=True, autoincrement=True)
    role_type = Column(String(64), nullable=False)
    name = Column(String(64), nullable=False)
    description = Column(String(255))
    unlock_condition = Column(Text)
    unlock_type = Column(String(32))
    unlock_value = Column(Integer)

# 用户皮肤表
class UserSkin(Base):
    __tablename__ = "user_skins"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role_type = Column(String(64), nullable=False)
    skin_id = Column(Integer, nullable=False)
    equipped = Column(Boolean, default=False)