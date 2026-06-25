"""
业务异常层级定义。

所有业务异常继承 EchoSoulException，便于全局异常处理器统一捕获。
系统级异常（ValueError、RuntimeError 等）不在此处定义，由全局兜底处理器处理。
"""


class EchoSoulException(Exception):
    """所有业务异常的基类"""
    pass


# ---- 认证 ----
class AuthenticationError(EchoSoulException):
    """认证失败（token 无效、过期等）"""
    pass


class UserNotFoundError(EchoSoulException):
    """用户不存在"""
    pass


class DuplicateUserError(EchoSoulException):
    """用户名已存在"""
    pass


# ---- AI 服务 ----
class AIServiceError(EchoSoulException):
    """AI 模型调用失败"""
    pass


class EmotionAnalysisError(EchoSoulException):
    """情感分析失败"""
    pass


class MemoryExtractionError(EchoSoulException):
    """记忆提取失败"""
    pass


# ---- 记忆 ----
class MemoryStoreError(EchoSoulException):
    """记忆存储失败"""
    pass


class MemoryRetrievalError(EchoSoulException):
    """记忆检索失败"""
    pass


class VectorSyncError(EchoSoulException):
    """向量同步失败"""
    pass


# ---- 好感度 ----
class AffectionUpdateError(EchoSoulException):
    """好感度更新失败"""
    pass


# ---- 数据库 ----
class DatabaseNotInitializedError(RuntimeError):
    """数据库未初始化（系统级错误，非业务异常）"""
    pass


class RedisNotInitializedError(RuntimeError):
    """Redis 未初始化（系统级错误，非业务异常）"""
    pass
