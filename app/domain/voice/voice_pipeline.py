"""
语音对话管线 — 阿里百炼 FunASR → LLM 流式 → CosyVoice TTS

在 FastAPI WebSocket 内异步执行。
"""
import asyncio
import logging
from typing import AsyncGenerator

from app.domain.voice.asr_service import convert_webm_to_pcm, transcribe_sync
from app.domain.voice.tts_service import synthesize_stream

logger = logging.getLogger(__name__)


class VoicePipeline:
    """语音对话管线。"""

    def __init__(self):
        self._interrupted = False

    def interrupt(self) -> None:
        self._interrupted = True
        logger.info("[Voice] 打断信号已设置")

    async def process(
        self, audio_chunks: list[bytes], user_id: str, role_type: str
    ) -> AsyncGenerator[dict, None]:
        """
        处理语音对话：WebM 音频 → ASR → LLM → TTS → audio-chunk。

        Yields:
            asr-result / asr-final → audio-chunk / speech-end
        """
        self._interrupted = False
        loop = asyncio.get_running_loop()

        # ---- 1. 音频格式转换: WebM → PCM 16kHz ----
        yield {"type": "asr-result", "text": "（处理音频中...）"}
        try:
            pcm = await loop.run_in_executor(None, convert_webm_to_pcm, audio_chunks)
        except Exception as e:
            logger.error("[Voice] 音频转换失败: %s", e)
            yield {"type": "asr-final", "text": ""}
            return

        if self._interrupted:
            yield {"type": "speech-end"}
            return

        # ---- 2. ASR: PCM → 文本 ----
        yield {"type": "asr-result", "text": "（语音识别中...）"}
        try:
            user_text = await loop.run_in_executor(None, transcribe_sync, pcm)
        except Exception as e:
            logger.error("[Voice] ASR 失败: %s", e)
            yield {"type": "asr-final", "text": ""}
            return

        if not user_text.strip():
            yield {"type": "asr-final", "text": ""}
            return

        yield {"type": "asr-final", "text": user_text}
        logger.info("[Voice] ASR 完成: %s", user_text[:80])

        if self._interrupted:
            yield {"type": "speech-end"}
            return

        # ---- 3. LLM 回复生成（复用 Celery 文字通道逻辑） ----
        ai_reply = await self._generate_reply(user_text, user_id, role_type)
        if not ai_reply:
            yield {"type": "speech-end"}
            return

        logger.info("[Voice] LLM 回复: %s", ai_reply[:80])

        # ---- 4. 提取表情标签 + 逐句拆分 ----
        import re
        EXPRESSION_MAP = {"joy": 0, "sad": 1, "surprise": 2, "anger": 3, "neutral": 4}
        expr_tags = re.findall(r"\[(joy|sad|surprise|anger|neutral)\]", ai_reply)
        expressions = [EXPRESSION_MAP[t] for t in expr_tags] if expr_tags else [4]
        logger.info("[Voice] 表情标签: %s → indices: %s", expr_tags, expressions)

        # 按 [tag] 拆分句子，每个句子带自己的表情
        sentences = re.split(r"\[(?:joy|sad|surprise|anger|neutral)\]", ai_reply)
        sentences = [s.strip() for s in sentences if s.strip()]

        if self._interrupted:
            yield {"type": "speech-end"}
            return

        # ---- 5. TTS: 逐句合成，每句带独立表情 ----
        try:
            for i, sentence in enumerate(sentences):
                if self._interrupted:
                    break
                expr = [expressions[i]] if i < len(expressions) else [4]
                logger.info("[Voice] 句子 %d/%d: expr=%s text=%s", i+1, len(sentences), expr, sentence[:40])
                async for audio_data in synthesize_stream(sentence, role_type):
                    if self._interrupted:
                        break
                    audio_data["expressions"] = expr
                    yield audio_data
        except Exception as e:
            logger.error("[Voice] TTS 失败: %s", e)

        yield {"type": "speech-end"}

    async def _generate_reply(
        self, user_text: str, user_id: str, role_type: str
    ) -> str:
        """快速 LLM 回复 — 跳过 Celery/情绪分析，直接调模型。"""
        try:
            from app.core.config import get_settings
            from app.domain.roles.catalog import RoleCatalog
            from app.domain.agent.prompts import PromptFactory
            from langchain.chat_models import init_chat_model
            from langchain_core.messages import SystemMessage, HumanMessage

            settings = get_settings()

            # 轻量 LLM（跳过情绪分析，voice 模式专用）
            llm = init_chat_model(
                model=settings.LLM_MODEL,
                model_provider="openai",
                temperature=0.8,
                max_tokens=200,  # 语音回复简短但完整
                api_key=settings.DASHSCOPE_API_KEY,
                base_url=settings.DASHSCOPE_BASE_URL,
            )

            role = RoleCatalog.get_role(role_type)
            system_prompt = (
                f"你是{role.name}。{role.persona}\n"
                f"说话风格：{role.style}\n"
                "你正在和用户进行实时语音对话。\n"
                "请用自然的口语简短回复，1-2句话即可，必须说完整句子。\n"
                "每次回复的前面必须插入一个表情标签: [joy]开心/[sad]难过/[surprise]惊讶/[anger]生气。\n"
                "根据你的回复内容选择合适的表情，例如:\n"
                "  开心时: '[joy]当然啦！我也超喜欢！'\n"
                "  难过时: '[sad]这个结局确实让人想哭...'\n"
                "  惊讶时: '[surprise]什么？！不会吧？！'\n"
                "  生气时: '[anger]那也太过分了！'"
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_text),
            ]

            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, llm.invoke, messages)
            return resp.content.strip()
        except Exception as e:
            logger.error("[Voice] LLM 快速调用失败: %s", e, exc_info=True)
            return ""
