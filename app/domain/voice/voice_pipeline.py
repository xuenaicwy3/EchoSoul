"""
语音对话管线 — 流式 ASR → LLM → TTS

LLM 流式逐 Token 产出 → 句子级缓冲 → 整句送 TTS → 音频流即时推送。
首句延迟 ~1-2s（LLM 首 Token + 首句完整后即送 TTS），边生成边播放。
"""
import asyncio
import logging
import re
from typing import AsyncGenerator

from app.domain.voice.asr_service import convert_webm_to_pcm, transcribe_sync
from app.domain.voice.tts_service import synthesize_stream

logger = logging.getLogger(__name__)

EXPRESSION_MAP = {"joy": 0, "sad": 1, "surprise": 2, "anger": 3, "neutral": 4}
SENTENCE_END = re.compile(r"[。！？\n]")
EXPR_TAG = re.compile(r"\[(joy|sad|surprise|anger|neutral)\]")


class VoicePipeline:
    """流式语音对话管线。"""

    def __init__(self):
        self._interrupted = False

    def interrupt(self) -> None:
        self._interrupted = True
        logger.info("[Voice] 打断信号已设置")

    async def process(
        self, audio_chunks: list[bytes], user_id: str, role_type: str
    ) -> AsyncGenerator[dict, None]:
        """处理语音对话: WebM → ASR → LLM(stream) → TTS(逐句) → audio-chunk。"""
        self._interrupted = False
        loop = asyncio.get_running_loop()

        # ---- 1. 音频格式转换 ----
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

        # ---- 2. ASR ----
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
        logger.info("[Voice] ASR: %s", user_text[:80])
        if self._interrupted:
            yield {"type": "speech-end"}
            return

        # ---- 3. LLM 流式 + 逐句 TTS ----
        has_audio = False
        try:
            async for sentence, expression in self._generate_reply_stream(
                user_text, user_id, role_type
            ):
                if self._interrupted:
                    break
                if not sentence.strip():
                    continue
                logger.info("[Voice] TTS句子: expr=%d text=%s", expression, sentence[:40])
                async for audio_data in synthesize_stream(sentence, role_type):
                    if self._interrupted:
                        break
                    audio_data["expressions"] = [expression]
                    has_audio = True
                    yield audio_data
        except Exception as e:
            logger.error("[Voice] LLM/TTS 异常: %s", e, exc_info=True)

        yield {"type": "speech-end"}

    async def _generate_reply_stream(
        self, user_text: str, user_id: str, role_type: str
    ) -> AsyncGenerator[tuple[str, int], None]:
        """流式 LLM 回复 —— 逐 Token 产出，按句子边界 yield (sentence, expression_index)。

        缓冲机制:
          1. LLM.stream() 逐 token 产出
          2. 累积到 buffer
          3. 检测到句子结束符（。！？\\n）→ yield 完整句子 + 当前表情
          4. 新表情标签出现时更新当前表情
          5. 剩余 buffer 在最后 flush

        效果: 首句 ~1-2s 即可开始 TTS，无需等全文生成完毕。
        """
        try:
            from app.core.config import get_settings
            from app.domain.roles.catalog import RoleCatalog
            from langchain.chat_models import init_chat_model
            from langchain_core.messages import SystemMessage, HumanMessage

            settings = get_settings()

            llm = init_chat_model(
                model=settings.LLM_MODEL,
                model_provider="openai",
                temperature=0.8,
                max_tokens=200,
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

            # 队列: 线程池中 sync stream → 推入 async queue → 异步消费
            queue: asyncio.Queue = asyncio.Queue()

            def _run_stream():
                try:
                    for chunk in llm.stream(messages):
                        if self._interrupted:
                            break
                        content = chunk.content if hasattr(chunk, "content") else ""
                        asyncio.run_coroutine_threadsafe(
                            queue.put(("token", content)),
                            loop,
                        )
                    asyncio.run_coroutine_threadsafe(
                        queue.put(("done", None)),
                        loop,
                    )
                except Exception as e:
                    asyncio.run_coroutine_threadsafe(
                        queue.put(("error", str(e))),
                        loop,
                    )

            loop.run_in_executor(None, _run_stream)

            buffer = ""
            current_expr = 4  # 默认 neutral

            while True:
                msg_type, payload = await queue.get()
                if msg_type == "done":
                    break
                elif msg_type == "error":
                    logger.error("[Voice] LLM stream 异常: %s", payload)
                    break
                elif msg_type == "token":
                    if not payload:
                        continue
                    buffer += payload

                    # 检测表情标签 [joy] → 更新当前表情
                    while True:
                        tag_match = EXPR_TAG.search(buffer)
                        if not tag_match:
                            break
                        before = buffer[:tag_match.start()].strip()
                        if before:
                            yield (before, current_expr)
                        current_expr = EXPRESSION_MAP.get(tag_match.group(1), 4)
                        buffer = buffer[tag_match.end():]

                    # 按句子边界 yield
                    while True:
                        end_match = SENTENCE_END.search(buffer)
                        if not end_match:
                            break
                        sentence = buffer[:end_match.end()].strip()
                        buffer = buffer[end_match.end():]
                        if sentence:
                            yield (sentence, current_expr)

            # flush 剩余 buffer
            if buffer.strip() and not self._interrupted:
                yield (buffer.strip(), current_expr)

        except Exception as e:
            logger.error("[Voice] LLM 流式调用失败: %s", e, exc_info=True)
