"""
聊天历史管理器（基于 LangChain Chroma，不下载任何模型）
"""
import logging
from datetime import datetime
from typing import List, Dict

from langchain_chroma import Chroma
from langchain_core.embeddings import FakeEmbeddings

logger = logging.getLogger(__name__)


class ChatHistoryManager:
    def __init__(self, persist_directory: str = "./chroma_data"):
        # 创建一个假的嵌入模型，它不会触发任何下载
        self.embeddings = FakeEmbeddings(size=1)  # size 随意，不会真正调用
        self.persist_directory = persist_directory
        self.collection_name = "chat_history"

        # 先删除旧集合（避免遗留配置）
        try:
            # Chroma 的 delete_collection 需要通过 client
            import chromadb  # 仅用于删除操作，用完即弃
            client = chromadb.PersistentClient(path=self.persist_directory)
            client.delete_collection(self.collection_name)
            logger.info("已删除旧的聊天历史集合")
        except Exception:
            pass

        # 创建全新的 LangChain Chroma 实例
        self.store = Chroma(
            collection_name=self.collection_name,
            embedding_function=self.embeddings,
            persist_directory=self.persist_directory,
        )
        logger.info("聊天历史管理器初始化完成（LangChain Chroma）")

    def add_message(self, user_id: str, role_type: str, sender: str, message: str):
        timestamp = datetime.now().isoformat()
        # 使用 LangChain 的 add_texts 方法，自动生成 ID
        self.store.add_texts(
            texts=[message],
            metadatas=[{
                "user_id": user_id,
                "role_type": role_type,
                "sender": sender,
                "timestamp": timestamp
            }]
        )
        logger.info("历史消息已存储: user_id=%s, sender=%s, role=%s", user_id, sender, role_type)

    def get_history(self, user_id: str, role_type: str, limit: int = 100) -> List[Dict]:
        # 使用 Chroma 原生过滤（需要获取底层 collection）
        collection = self.store._collection
        results = collection.get(
            where={
                "$and": [
                    {"user_id": user_id},
                    {"role_type": role_type}
                ]
            },
            include=["documents", "metadatas"]
        )
        if not results["ids"]:
            return []
        messages = []
        for doc, meta in zip(results["documents"] or [], results["metadatas"] or []):
            messages.append({
                "sender": meta["sender"],
                "message": doc,
                "timestamp": meta["timestamp"]
            })
        messages.sort(key=lambda x: x["timestamp"])
        logger.info("加载聊天历史: user=%s, role=%s, 共 %d 条", user_id, role_type, len(messages))
        return messages[-limit:]

    def delete_history(self, user_id: str, role_type: str):
        collection = self.store._collection
        results = collection.get(
            where={
                "$and": [
                    {"user_id": user_id},
                    {"role_type": role_type}
                ]
            }
        )
        if results["ids"]:
            collection.delete(ids=results["ids"])
            logger.info("已删除聊天历史: user=%s, role=%s, 共 %d 条", user_id, role_type, len(results["ids"]))