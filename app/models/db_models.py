from sqlalchemy import Column, Integer, String, Float, Text, DateTime, func, PrimaryKeyConstraint
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