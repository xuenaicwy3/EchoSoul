"""
记忆服务（Chroma HTTP 客户端模式，多进程安全）
"""
import logging
import uuid
from datetime import datetime
from chromadb import HttpClient
from app.config import Settings
from app.prompts import PromptFactory
from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class MemoryService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._embedding_dim = None  # 延迟获取

        # 嵌入模型（非测试模式下才会真正调用）
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
        # 连接本地 Chroma 服务
        self.client = HttpClient(host="localhost", port=8000)
        self.collection = self.client.get_or_create_collection(
            name=settings.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info("记忆服务初始化完成（Chroma HTTP 客户端）")

    def _get_dim(self) -> int:
        """自动获取向量维度，按优先级：1. Chroma已有数据 2. 调用一次嵌入API 3. 配置fallback"""
        if self._embedding_dim is not None:
            return self._embedding_dim

        # 1. 尝试从 Chroma 集合中已有的记录获取维度
        try:
            if self.collection.count() > 0:
                sample = self.collection.peek(limit=1)
                if sample and sample.get("embeddings") and sample["embeddings"][0]:
                    dim = len(sample["embeddings"][0])
                    self._embedding_dim = dim
                    logger.info(f"从 Chroma 获取到向量维度: {dim}")
                    return dim
        except Exception as e:
            logger.warning(f"从 Chroma 获取维度失败: {e}")

        # 2. 非测试模式下，调用一次嵌入 API 获取维度（会消耗少量 Token）
        if not self.settings.TEST_MODE:
            try:
                test_emb = self.embeddings.embed_query("dimension test")
                dim = len(test_emb)
                self._embedding_dim = dim
                logger.info(f"通过嵌入API获取到向量维度: {dim}")
                return dim
            except Exception as e:
                logger.error(f"通过嵌入API获取维度失败: {e}")

        # 3. 回退到配置文件
        fallback = self.settings.EMBEDDING_DIM
        logger.warning(f"使用配置中的向量维度: {fallback}")
        self._embedding_dim = fallback
        return fallback

    def store(self, user_id: str, user_msg: str, ai_reply: str,
              emotion: dict, role_type: str) -> None:
        # 测试模式
        if self.settings.TEST_MODE:
            dim = self._get_dim()
            fake_summary = f"[测试记忆] 用户说: {user_msg[:30]}... | AI回复: {ai_reply[:30]}..."
            fake_embedding = [0.0] * dim
            now = datetime.now(timezone.utc).isoformat()
            try:
                self.collection.add(
                    ids=[str(uuid.uuid4())],
                    documents=[fake_summary],
                    metadatas=[{
                        "user_id": user_id,
                        "role_type": role_type,
                        "emotion": emotion.get("label"),
                        "intensity": emotion.get("score"),
                        "timestamp": now
                    }],
                    embeddings=[fake_embedding]
                )
                logger.info("记忆已存储（测试模式）: 1 条")
            except Exception as e:
                logger.error("记忆存储失败（测试模式）: %s", e)
            return

        # 正常模式
        prompt = PromptFactory.memory_extraction(user_msg, ai_reply)
        response = self.summary_llm.invoke(prompt)
        raw = response.content.strip()
        if raw == "无" or not raw:
            return
        summaries = [s.strip() for s in raw.split("\n") if s.strip() != "无"]
        if not summaries:
            return

        embeddings_list = self.embeddings.embed_documents(summaries)
        # 顺便缓存维度（如果还未设置）
        if self._embedding_dim is None and embeddings_list:
            self._embedding_dim = len(embeddings_list[0])

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
        # 测试模式：直接返回假记忆，不调用嵌入
        if self.settings.TEST_MODE:
            return "[测试记忆] 这是假的历史记忆，用于压测。"

        # 正常模式
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
                logger.info("暂无记忆")
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