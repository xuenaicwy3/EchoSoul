import asyncio
import base64
import logging
from dashscope.audio.tts_v2 import SpeechSynthesizer

logger = logging.getLogger(__name__)

class TTSService:
    # 角色-音色映射
    VOICE_MAP = {
        "温柔贤淑型": "longanhuan",
        "日系动漫型": "longanhuan_v3",
        "高冷御姐型": "longling_v3",
        "傲娇辣妹型": "longxian_v3",
        "甜美校花型": "longanhuan",
        "软萌可爱型": "longling_v3",
        "元气少女型": "longxian_v3",
        "清冷仙气型": "longling_v3",
    }

    def __init__(self, model: str = "cosyvoice-v3-flash"):
        self.model = model

    async def synthesize(self, text: str, role_type: str) -> bytes | None:
        """
        异步合成语音，返回 MP3 字节，失败返回 None
        """
        voice = self.VOICE_MAP.get(role_type, "longanhuan")
        try:
            # 在线程池中执行同步的 dashscope 调用，避免阻塞事件循环
            loop = asyncio.get_running_loop()
            audio_data = await loop.run_in_executor(
                None,
                self._synthesize_sync,
                text,
                voice
            )
            if audio_data:
                return audio_data
            else:
                logger.warning("TTS 返回空数据")
                return None
        except Exception as e:
            logger.error(f"TTS 合成失败: {e}")
            return None

    def _synthesize_sync(self, text: str, voice: str) -> bytes | None:
        synthesizer = SpeechSynthesizer(model=self.model, voice=voice)
        return synthesizer.call(text)