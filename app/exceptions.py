"""
业务异常定义
便于在全局异常处理器中区分业务错误和系统错误
"""

class EchoSoulException(Exception):
    """所有业务异常的基类"""
    pass

class EmotionAnalysisError(EchoSoulException):
    """情感分析失败"""
    pass

class MemoryStoreError(EchoSoulException):
    """记忆存储失败"""
    pass

class AffectionUpdateError(EchoSoulException):
    """好感度更新失败"""
    pass