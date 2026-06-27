"""
阿里百炼 CosyVoice 流式语音合成服务。

基于 DashScope WebSocket 双向流式协议。
支持实时逐句合成 + 返回 base64 音频块。
"""
import asyncio
import base64
import io
import json
import logging
import math
import struct
import wave
from typing import AsyncGenerator

import dashscope
from dashscope.audio.tts_v2 import (
    SpeechSynthesizer,
    ResultCallback,
    AudioFormat,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
dashscope.api_key = settings.DASHSCOPE_API_KEY
dashscope.base_websocket_api_url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"

# 音色映射：角色 → CosyVoice 音色
# CosyVoice V3-Flash 甜美女声
ROLE_VOICE_MAP = {
    "日系动漫型": "longxiaochun_v3",   # 龙小纯 v3 — 活泼甜美女声
    "高冷御姐型": "longxiaoxia_v3",    # 龙小夏 v3 — 成熟御姐声线
    "傲娇辣妹型": "longxiaochun_v3",   # V3 无 longyue，用龙小纯替代
    "甜美校花型": "longxiaochun_v3",   # 龙小纯 v3 — 温柔甜美女声
    "软萌可爱型": "longxiaochun_v3",   # V3 无 longtong，用龙小纯替代
    "温柔贤淑型": "longxiaochun_v3",   # 龙小纯 v3 — 温柔甜美女声
    "元气少女型": "longxiaochun_v3",   # 龙小纯 v3 — 元气活泼女声
    "清冷仙气型": "longxiaoxia_v3",    # 龙小夏 v3 — 清冷仙气声线
}


def _rms_volume(audio_bytes: bytes, sample_width: int = 2) -> float:
    """计算 PCM 音频块的 RMS 音量（归一化到 0~1）。"""
    if not audio_bytes:
        return 0.0
    count = len(audio_bytes) // sample_width
    if count == 0:
        return 0.0
    fmt = {1: "b", 2: "h", 4: "i"}.get(sample_width, "h")
    samples = struct.unpack(f"<{count}{fmt}", audio_bytes)
    rms = math.sqrt(sum(s * s for s in samples) / count)
    return min(1.0, rms / 32768.0)


class TTSStreamCallback(ResultCallback):
    """CosyVoice 流式回调，收集音频块。"""

    def __init__(self):
        self.chunks: list[bytes] = []
        self.texts: list[str] = []
        self._done = asyncio.Event()

    def on_open(self) -> None:
        logger.debug("[TTS] 连接建立")

    def on_data(self, data: bytes) -> None:
        self.chunks.append(data)

    def on_event(self, message: str) -> None:
        try:
            msg = json.loads(message)
            output = msg.get("payload", {}).get("output", {})
            original_text = output.get("original_text", "")
            if original_text:
                self.texts.append(original_text)
        except Exception:
            pass

    def on_complete(self) -> None:
        logger.info("[TTS] 合成完成: %d chunks", len(self.chunks))
        self._done.set()

    def on_error(self, message: str) -> None:
        logger.error("[TTS] 错误: %s", message)
        self._done.set()

    def on_close(self) -> None:
        self._done.set()


async def synthesize_stream(
    text: str,
    role_type: str = "温柔贤淑型",
    speech_rate: float = 1.0,
) -> AsyncGenerator[dict, None]:
    """
    流式 TTS：输入文本 → 输出 audio-chunk 消息。

    Yields:
        {"type": "audio-chunk", "audio": base64, "volumes": [...],
         "slice_length_ms": 20, "text": "...", "expressions": []}
    """
    voice = ROLE_VOICE_MAP.get(role_type, "longxiaochun_v3")
    logger.info("[TTS] 开始合成: voice=%s text=%s", voice, text[:50])

    callback = TTSStreamCallback()
    synthesizer = SpeechSynthesizer(
        model="cosyvoice-v3-flash",
        voice=voice,
        format=AudioFormat.WAV_16000HZ_MONO_16BIT,
        speech_rate=speech_rate,
        volume=50,
        callback=callback,
    )

    # 在线程池中执行同步 WebSocket 调用，15s 超时保护
    loop = asyncio.get_running_loop()

    def _synthesize() -> None:
        try:
            synthesizer.streaming_call(text)
            synthesizer.streaming_complete()
        except Exception as e:
            logger.error("[TTS] 合成线程异常: %s", e)
            callback._done.set()  # 确保不永久等待

    future = loop.run_in_executor(None, _synthesize)
    try:
        await asyncio.wait_for(future, timeout=15)
    except asyncio.TimeoutError:
        logger.warning("[TTS] 合成超时(15s)，跳过")

    # 等待回调完成（最多 10s）
    try:
        await asyncio.wait_for(callback._done.wait(), timeout=10)
    except asyncio.TimeoutError:
        logger.warning("[TTS] 回调等待超时")

    if not callback.chunks:
        logger.warning("[TTS] 无音频数据")
        return

    # 合并所有 WAV 块，计算 volumes
    full_wav = b"".join(callback.chunks)

    if not full_wav:
        logger.warning("[TTS] 无音频数据")
        return

    # 从 WAV 中提取 PCM 数据并计算 volumes
    try:
        wav_buf = io.BytesIO(full_wav)
        with wave.open(wav_buf, "rb") as wf:
            sample_rate = wf.getframerate()
            pcm = wf.readframes(wf.getnframes())

        # 计算 volumes（每 20ms 一个 RMS 值）
        bytes_per_slice = int(sample_rate * 2 * 20 / 1000)
        volumes = []
        for i in range(0, len(pcm), bytes_per_slice):
            chunk = pcm[i:i + bytes_per_slice]
            volumes.append(round(_rms_volume(chunk), 3))
    except Exception as e:
        logger.error("[TTS] 音量计算失败: %s", e)
        volumes = []

    audio_b64 = base64.b64encode(full_wav).decode()

    yield {
        "type": "audio-chunk",
        "audio": audio_b64,
        "volumes": volumes,
        "slice_length_ms": 20,
        "text": text,
        "expressions": [],
    }
