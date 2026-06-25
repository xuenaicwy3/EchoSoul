"""
ChromaDB 客户端封装。

统一管理三层向量集合的创建和访问。
"""
import logging
from typing import Tuple

from chromadb import HttpClient
from chromadb.api import Collection

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 模块级客户端缓存
_client: HttpClient | None = None
_collections: Tuple[Collection, Collection, Collection] | None = None


def get_chroma_client() -> HttpClient:
    """获取 ChromaDB HTTP 客户端单例。"""
    global _client
    if _client is None:
        _client = HttpClient(host="localhost", port=8000)
        logger.info("ChromaDB 客户端已连接")
    return _client


def get_vector_collections() -> Tuple[Collection, Collection, Collection]:
    """获取三层记忆集合: (facts, emotions, milestones)。"""
    global _collections
    if _collections is not None:
        return _collections

    settings = get_settings()
    client = get_chroma_client()

    facts_col = client.get_or_create_collection(
        name=settings.VECTOR_FACTS_COL,
        metadata={"hnsw:space": "cosine"},
    )
    emotions_col = client.get_or_create_collection(
        name=settings.VECTOR_EMOTIONS_COL,
        metadata={"hnsw:space": "cosine"},
    )
    milestones_col = client.get_or_create_collection(
        name=settings.VECTOR_MILESTONES_COL,
        metadata={"hnsw:space": "cosine"},
    )
    _collections = (facts_col, emotions_col, milestones_col)
    logger.info(
        "三层集合就绪: facts=%d emotions=%d milestones=%d",
        facts_col.count(), emotions_col.count(), milestones_col.count(),
    )
    return _collections
