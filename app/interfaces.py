"""
核心服务抽象接口
采用依赖倒置原则，所有高层模块依赖这些抽象，而非具体实现
"""
from abc import ABC, abstractmethod
from typing import Dict, List

class EmotionAnalyzer(ABC):
    """情绪分析器接口"""
    @abstractmethod
    def analyze(self, text: str) -> dict:
        """
        分析文本情绪
        Returns:
            {"label": str, "score": float}  例如 {"label": "joy", "score": 0.95}
        """
        ...

    @staticmethod
    @abstractmethod
    def get_emotion_style(label: str, intensity: float) -> str:
        """将情绪标签转换为对话策略文本"""
        ...

class MemoryManager(ABC):
    """记忆管理器接口"""
    @abstractmethod
    def store(self, user_id: str, user_msg: str, ai_reply: str,
              emotion: dict, role_type: str) -> None:
        """从一轮对话中提取关键信息并持久化"""
        ...

    @abstractmethod
    def retrieve(self, user_id: str, query: str) -> str:
        """根据当前查询检索相关记忆，返回格式化字符串"""
        ...

class AffectionManager(ABC):
    """好感度管理器接口"""
    @abstractmethod
    def get(self, user_id: str, role_type: str) -> Dict[str, float]:
        """获取四个维度的好感度值"""
        ...

    @abstractmethod
    def update(self, user_id: str, role_type: str, delta: Dict[str, float]) -> None:
        """更新好感度（delta 可为负数）"""
        ...

    @abstractmethod
    def calculate_delta(self, user_msg: str, ai_response: str, emotion: dict) -> Dict[str, float]:
        """根据本轮对话计算好感度变化量"""
        ...

    @abstractmethod
    def apply_decay(self) -> None:
        """对所有长时间未互动的记录执行衰减"""
        ...

    @abstractmethod
    def get_unlock_state(self, user_id: str, role_type: str) -> Dict:
        """根据当前好感度返回解锁状态"""
        ...