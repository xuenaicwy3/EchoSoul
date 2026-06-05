from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, func, PrimaryKeyConstraint, Boolean, Date, text, JSON, ForeignKey
from sqlalchemy.orm import relationship, DeclarativeBase


# ========== Base 定义 ==========
class Base(DeclarativeBase):
    pass

# 北京时间时区对象
BEIJING_TZ = ZoneInfo("Asia/Shanghai")

# ========== 聊天历史 ==========
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


# ========== 好感度 ==========
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


# ========== 共创叙事 ==========
class Story(Base):
    __tablename__ = "stories"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role_type = Column(String(64), nullable=False)
    title = Column(String(255))
    status = Column(String(32), default="active")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    nodes = relationship("StoryNode", back_populates="story", order_by="StoryNode.created_at")
    # 关键：添加 cascade 实现级联删除
    nodes = relationship("StoryNode", back_populates="story",
                         order_by="StoryNode.created_at",
                         cascade="all, delete-orphan")


class StoryNode(Base):
    __tablename__ = "story_nodes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    story_id = Column(Integer, ForeignKey('stories.id'), nullable=False)
    parent_node_id = Column(Integer, nullable=True)
    user_id = Column(String(64), nullable=True)
    type = Column(String(20), nullable=False)  # start / user_input / ai_output / ending
    content = Column(Text, nullable=False)
    choices = Column(JSON, nullable=True)
    selected_choice = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    story = relationship("Story", back_populates="nodes")



# ==================== 情感记忆系统（模块二） ====================

class UserFact(Base):
    """事实层：存储用户基础信息（姓名、生日、喜好等）"""
    __tablename__ = "user_facts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role_type = Column(String(64), nullable=False)
    key = Column(String(128), nullable=False)               # 事实类型，如 "name", "birthday", "likes"
    value = Column(Text, nullable=False)                    # 事实内容
    source = Column(String(32), default="extracted")        # extracted / manual
    created_at = Column(DateTime(timezone=True), server_default=text("(now() AT TIME ZONE 'utc')"))
    updated_at = Column(DateTime(timezone=True), server_default=text("(now() AT TIME ZONE 'utc')"),
                        onupdate=lambda: datetime.now(timezone.utc))

class EmotionRecord(Base):
    """情感层：记录每次对话的情感标签与得分"""
    __tablename__ = "emotion_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role_type = Column(String(64), nullable=False)
    label = Column(String(32), nullable=False)              # emotion label
    score = Column(Float, nullable=False)
    message = Column(Text, nullable=True)                   # 用户原话（可选）
    created_at = Column(DateTime(timezone=True), server_default=text("(now() AT TIME ZONE 'utc')"))

class RelationshipMilestone(Base):
    """关系层：记录共同事件、重要时刻、关系里程碑"""
    __tablename__ = "relationship_milestones"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role_type = Column(String(64), nullable=False)
    event = Column(String(255), nullable=False)             # 事件描述
    event_type = Column(String(32), nullable=False)         # first_chat, intimacy_level, special_moment
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("(now() AT TIME ZONE 'utc')"))


class UserMemorySummary(Base):
    """记忆摘要缓存"""
    __tablename__ = "user_memory_summaries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    role_type = Column(String(64), nullable=False)
    summary = Column(Text, nullable=False)
    emotion_count = Column(Integer, default=0)           # 生成摘要时的情感记录数
    fact_count = Column(Integer, default=0)              # 新增
    milestone_count = Column(Integer, default=0)         # 新增
    created_at = Column(DateTime(timezone=True), server_default=text("(now() AT TIME ZONE 'utc')"))
    updated_at = Column(DateTime(timezone=True), server_default=text("(now() AT TIME ZONE 'utc')"),
                        onupdate=lambda: datetime.now(timezone.utc))