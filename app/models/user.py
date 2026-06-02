import uuid
from sqlalchemy import Column, String
from app.database import Base

def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    username = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(String(128), nullable=False)