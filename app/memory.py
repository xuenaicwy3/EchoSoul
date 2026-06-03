"""
记忆服务（Chroma HTTP 客户端模式，多进程安全）
"""
import asyncio
import logging
import uuid
from datetime import datetime
from chromadb import HttpClient
from app.config import Settings
from app.prompts import PromptFactory
from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings

logger = logging.getLogger(__name__)

class MemoryService:
    def __init__(self, settings: Settings):
        self.settings = settings
        # 嵌入模型
        self.embeddings = DashScopeEmbeddings(
            model=settings.EMBED_MODEL,
            dashscope_api_key=settings.DASHSCOPE_API_KEY,
        )
        # 记忆摘要 LLM
        self.summary_llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",
            temperature=0.3,
            max_tokens=100,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
        )
        # 连接本地 Chroma 服务（HTTP，非嵌入式）
        self.client = HttpClient(host="localhost", port=8000)
        self.collection = self.client.get_or_create_collection(
            name=settings.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info("记忆服务初始化完成（Chroma HTTP 客户端）")

    def store(self, user_id: str, user_msg: str, ai_reply: str,
                    emotion: dict, role_type: str) -> None:
        prompt = PromptFactory.memory_extraction(user_msg, ai_reply)
        response = self.summary_llm.invoke(prompt)
        raw = response.content.strip()
        if raw == "无" or not raw:
            return
        summaries = [s.strip() for s in raw.split("\n") if s.strip() != "无"]
        if not summaries:
            return

        # 批量生成嵌入
        embeddings_list = self.embeddings.embed_documents(summaries)
        # 批量插入记忆
        ids = [str(uuid.uuid4()) for _ in summaries]
        now = datetime.now().isoformat()
        metadatas = [{
            "user_id": user_id,
            "role_type": role_type,
            "emotion": emotion.get("label"),
            "intensity": emotion.get("score"),
            "timestamp": now
        } for _ in summaries]

        try:
            self.collection.add(
                ids=ids,
                documents=summaries,
                metadatas=metadatas,
                embeddings=embeddings_list
            )
            logger.info("记忆已存储: %d 条", len(summaries))
        except Exception as e:
            logger.error("记忆存储失败: %s", e)

    def retrieve(self, user_id: str, query: str, role_type: str) -> str:
        try:
            emb = self.embeddings.embed_query(query)
            results = self.collection.query(
                query_embeddings=[emb],
                n_results=self.settings.MEMORY_TOP_K,
                where={
                    "$and": [
                        {"user_id": user_id},
                        {"role_type": role_type}
                    ]
                },
                include=["documents", "metadatas"]
            )
            docs = results.get("documents")
            if not docs or not docs[0]:
                logger.info("======暂无记忆=======")
                return "暂无记忆"
            memories = []
            for doc, meta in zip(docs[0], results["metadatas"][0]):
                mem = doc
                if meta.get("emotion"):
                    mem += f" (当时情绪:{meta['emotion']})"
                memories.append(mem)
            logger.info("检索到 %d 条记忆", len(memories))
            return "\n".join(memories)
        except Exception as e:
            logger.error("记忆检索失败: %s", e)
            return "暂无记忆"