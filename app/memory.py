"""
记忆服务
实现 MemoryManager 接口，使用 Chroma 向量数据库 + DashScope Embedding
"""
import logging
import uuid
import chromadb
from chromadb import PersistentClient
from datetime import datetime
from langchain.chat_models import init_chat_model
from langchain_community.embeddings import DashScopeEmbeddings
from app.config import Settings
from app.interfaces import MemoryManager
from app.exceptions import MemoryStoreError
from app.prompts import PromptFactory

logger = logging.getLogger(__name__)

class MemoryService(MemoryManager):
    """基于 Chroma 和百炼 Embedding 的记忆管理"""

    def __init__(self, settings: Settings):
        logger.info("初始化记忆服务，Chroma 路径=%s", settings.CHROMA_PATH)
        # DashScope 原生 Embedding（解决 OpenAI 兼容接口的 contents 字段问题）
        self.embeddings = DashScopeEmbeddings(
            model=settings.EMBED_MODEL,
            dashscope_api_key=settings.DASHSCOPE_API_KEY,
        )
        # Chroma 持久化客户端
        self.client = PersistentClient(path=settings.CHROMA_PATH)

        # 安全地获取或创建集合（不删除，避免并发问题）
        try:
            self.collection = self.client.get_collection(
                name=settings.COLLECTION_NAME,
                embedding_function=None,
            )
            logger.info("成功加载已有记忆集合")
        except Exception:
            # 集合不存在，创建新集合
            self.collection = self.client.create_collection(
                name=settings.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
                embedding_function=None,
            )
            logger.info("创建新的记忆集合")

        # 记忆摘要 LLM（轻量）
        self.summary_llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",
            temperature=0.3,
            max_tokens=100,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
        )
        self.settings = settings
        logger.info("记忆服务初始化完成")

    def store(self, user_id: str, user_msg: str, ai_reply: str,
              emotion: dict, role_type: str) -> None:
        """
        从一轮对话中提取用户关键信息，去重后存入向量库
        存储记忆，增加 role_type 隔离
        """
        try:
            # 生成记忆提取提示词并调用 LLM
            prompt = PromptFactory.memory_extraction(user_msg, ai_reply)
            response = self.summary_llm.invoke(prompt)
            raw = response.content.strip()
            logger.info("[Memory.store] 原始摘要: %s", raw)

            if raw == "无" or not raw:
                logger.info("[Memory.store] 摘要为'无'或空，跳过存储")
                return

            # 按行分割，每条一个记忆
            summaries = [s.strip() for s in raw.split("\n") if s.strip() != "无"]
            # if not summaries:
            #     logger.info("[Memory.store] 过滤后无有效摘要，跳过存储")
            #     return

            for summary in summaries:
                logger.info("[Memory.store] 处理摘要: %s", summary)
                emb = self.embeddings.embed_query(summary)
                # 去重检查：同一用户和角色下相似记忆
                # 修正：使用 $and 组合条件
                dup = self.collection.query(
                    query_embeddings=[emb],
                    n_results=1,
                    where={
                        "$and": [
                            {"user_id": user_id},
                            {"role_type": role_type}
                        ]
                    }
                )
                if (dup['distances'] and dup['distances'][0] and
                        dup['distances'][0][0] < self.settings.SIMILARITY_THRESHOLD):
                    logger.info("跳过重复记忆: %s", summary)
                    logger.info("[Memory.store] 相似度过高(%.4f)，跳过存储: %s", dup['distances'][0][0], summary)
                    continue

                doc_id = str(uuid.uuid4())
                # 存入 Chroma
                self.collection.add(
                    ids=[doc_id],
                    documents=[summary],
                    metadatas=[{
                        "user_id": user_id,
                        "role_type": role_type,  # 新增
                        "emotion": emotion.get("label"),
                        "intensity": emotion.get("score"),
                        "timestamp": datetime.now().isoformat()
                    }],
                    embeddings=[emb]
                )
                logger.info("记忆已存储: %s", summary)
        except Exception as e:
            logger.error("记忆存储失败: %s", e, exc_info=True)
            raise MemoryStoreError(f"记忆存储失败: {e}")

    def retrieve(self, user_id: str, query: str, role_type: str) -> str:
        """
        根据当前对话检索相关历史记忆
        检索记忆，增加 role_type 过滤
        """
        try:
            query_emb = self.embeddings.embed_query(query)
            # 修正：使用 $and 组合条件
            results = self.collection.query(
                query_embeddings=[query_emb],
                n_results=self.settings.MEMORY_TOP_K,
                where={
                    "$and": [
                        {"user_id": user_id},
                        {"role_type": role_type}
                    ]
                },
                include=["documents", "metadatas"]
            )
            # ---- 新增调试日志 ----
            docs = results.get("documents")
            if not docs or not docs[0]:
                logger.info("[Memory] 未检索到相关记忆 (user=%s, role=%s)", user_id[:8], role_type)
                return "暂无记忆"

            # 格式化返回，附带当时情绪标签
            memories = []
            for doc, meta in zip(docs[0], results["metadatas"][0]):
                mem = doc
                if meta.get("emotion"):
                    mem += f" (当时情绪:{meta['emotion']})"
                memories.append(mem)
            logger.info("检索到 %d 条记忆", len(memories))
            return "\n".join(memories)
        except Exception as e:
            logger.error("记忆检索失败: %s", e, exc_info=True)
            return "暂无记忆"




