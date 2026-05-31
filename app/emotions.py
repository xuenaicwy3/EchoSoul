"""
情绪分析服务
实现 EmotionAnalyzer 接口，使用阿里百炼 qwen-turbo 模型，通过 function calling 输出结构化结果
"""
import logging
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage, HumanMessage
from app.config import Settings
from app.interfaces import EmotionAnalyzer
from app.exceptions import EmotionAnalysisError
from app.models.schemas import EmotionResult
from app.prompts import PromptFactory

logger = logging.getLogger(__name__)


class EmotionService(EmotionAnalyzer):
    """基于 DashScope 的情绪分析实现"""

    def __init__(self, settings: Settings):
        logger.info("初始化情绪分析服务，模型=%s", settings.EMOTION_MODEL)
        # 初始化基础 LLM
        base_llm = init_chat_model(
            model=settings.EMOTION_MODEL,
            model_provider="openai",
            temperature=0.1,
            max_tokens=60,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
        )
        # 绑定结构化输出，强制模型返回符合 EmotionResult 的 JSON
        self.structured_llm = base_llm.with_structured_output(
            EmotionResult, method="function_calling"
        )
        logger.info("情绪分析服务初始化完成")

    def analyze(self, text: str) -> dict:
        """
        分析文本情绪
        若消息是角色选择指令，直接返回 neutral
        """
        logger.info("开始情绪分析，文本长度=%d", len(text))

        # 过滤角色选择消息，避免误判为 desire 情绪
        # skip_keywords = ["我想要一个", "我要一个", "选择角色", "换个角色"]
        # if any(kw in text for kw in skip_keywords):
        #     logger.debug("角色选择消息，跳过情绪分析")
        #     return {"label": "neutral", "score": 1.0}

        try:
            # 调用结构化 LLM
            result: EmotionResult = self.structured_llm.invoke([
                SystemMessage(content=PromptFactory.emotion_analysis_system()),
                HumanMessage(content=PromptFactory.emotion_analysis_user(text))
            ])
            logger.info("情绪分析完成: label=%s, score=%.2f", result.label, result.score)
            return {"label": result.label, "score": round(result.score, 4)}
        except Exception as e:
            logger.error("情绪分析失败: %s", e, exc_info=True)
            raise EmotionAnalysisError(f"情绪分析失败: {e}")

    @staticmethod
    def get_emotion_style(label: str, intensity: float) -> str:
        """
        将情绪标签转换为对话策略提示文本
        当置信度 > 0.8 时，额外强调情绪强度
        """
        strategies = {
            "sadness": "感知到用户情绪低落，请表达共情，温柔安慰。",
            "joy": "用户心情愉快，用同样兴奋的语气回应。",
            "anger": "用户可能生气，请保持冷静，表示理解并尝试缓和情绪。",
            "fear": "用户感到害怕或焦虑，给予安全感。",
            "love": "用户表达了爱意或温暖，温柔回应但保持边界。",
            "surprise": "用户惊讶，表达好奇并延续话题。",
            "neutral": "情绪平和，正常聊天。"
        }
        base = strategies.get(label, "请根据角色性格自然回应。")
        if intensity > 0.8:
            base += " 情绪强烈，请特别关注。"
        return base