"""
阿里百炼 FunASR 实时语音识别服务。

基于 DashScope WebSocket 双向流式协议。
"""
import asyncio
import logging
import threading
from typing import Callable

import dashscope
from dashscope.audio.asr import (
    Recognition,
    RecognitionCallback,
    RecognitionResult,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
dashscope.api_key = settings.DASHSCOPE_API_KEY
dashscope.base_websocket_api_url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"


class ASRCallback(RecognitionCallback):
    """FunASR 流式识别回调。"""

    def __init__(self, on_text: Callable[[str, bool], None]):
        self.on_text = on_text  # (text, is_final)

    def on_open(self) -> None:
        logger.info("[ASR] WebSocket 连接成功")

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if "text" in sentence:
            text = sentence["text"]
            is_final = RecognitionResult.is_sentence_end(sentence)
            self.on_text(text, is_final)

    def on_error(self, result) -> None:
        logger.error("[ASR] 错误: %s", result.message)

    def on_complete(self) -> None:
        logger.info("[ASR] 识别完成")

    def on_close(self) -> None:
        logger.info("[ASR] 连接关闭")


class ASRService:
    """实时语音识别服务（WebSocket 双向流）。"""

    def __init__(self):
        self._recognition: Recognition | None = None

    def transcribe_stream(
        self,
        sample_rate: int = 16000,
        audio_format: str = "pcm",
        language: str = "zh",
    ) -> tuple[Recognition, Callable[[bytes], None], Callable[[], None]]:
        """
        创建流式识别会话。

        Returns:
            (recognition, send_audio, stop)
            - recognition: Recognition 实例
            - send_audio: 发送音频帧 (bytes)
            - stop: 停止识别
        """
        # 临时积累文本，直到句子结束
        accumulated: list[str] = []
        results: list[dict] = []

        def on_text(text: str, is_final: bool) -> None:
            accumulated.append(text)
            logger.debug("[ASR] 片段: '%s' final=%s", text, is_final)

        callback = ASRCallback(on_text=on_text)
        recognition = Recognition(
            model="fun-asr-realtime",
            format=audio_format,
            sample_rate=sample_rate,
            callback=callback,
            semantic_punctuation_enabled=False,  # VAD 模式，适合对话交互
        )

        def send_audio(chunk: bytes) -> None:
            """发送 PCM 音频帧（16kHz, 16bit, mono）。"""
            recognition.send_audio_frame(chunk)

        def stop() -> dict:
            """停止识别，返回 {text, ...} 或空。"""
            recognition.stop()
            text = "".join(accumulated)
            # 用线程安全的方式获取结果
            return {"text": text, "is_final": True}

        self._recognition = recognition
        return recognition, send_audio, stop

    def start(self) -> Recognition:
        """启动识别（和 send_audio 配对使用）。"""
        if self._recognition:
            self._recognition.start()
            return self._recognition
        raise RuntimeError("请先调用 transcribe_stream() 创建会话")


# ---- 工具：将浏览器 WebM/Opus 音频转为 PCM 16kHz ----
def convert_webm_to_pcm(webm_chunks: list[bytes]) -> bytes:
    """
    将浏览器 MediaRecorder 录制的 WebM/Opus 音频转为 PCM 16kHz 16bit mono。

    注意：需要 ffmpeg 在 PATH 中。这是在 Celery/线程池中执行的 CPU 密集操作。
    """
    import subprocess
    import tempfile
    import os

    # 拼接所有 WebM 块
    webm_data = b"".join(webm_chunks)

    # 写入临时文件
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(webm_data)
        webm_path = f.name

    pcm_path = webm_path + ".pcm"
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", webm_path,
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1", pcm_path,
            ],
            capture_output=True, timeout=30,
            check=True,
        )
        with open(pcm_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(webm_path) if os.path.exists(webm_path) else None
        os.unlink(pcm_path) if os.path.exists(pcm_path) else None


# ---- 同步包装器 ----
def transcribe_sync(audio_pcm: bytes, sample_rate: int = 16000) -> str:
    """同步语音识别（将 PCM 写入临时 WAV 文件，调用 FunASR 非流式 API）。"""
    import tempfile
    import wave
    import os
    from http import HTTPStatus

    # 写临时 WAV 文件（FunASR call() 需要文件路径）
    wav_path = None
    try:
        fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_pcm)

        recognition = Recognition(
            model="fun-asr-realtime",
            format="wav",
            sample_rate=sample_rate,
            callback=None,
        )
        result = recognition.call(wav_path)
        if result.status_code == HTTPStatus.OK:
            sentence = result.get_sentence()
            if isinstance(sentence, list):
                return "".join(s.get("text", "") for s in sentence)
            if isinstance(sentence, dict):
                return sentence.get("text", "")
            return str(sentence)
        logger.error("[ASR] 同步识别失败: %s", result.message)
        return ""
    except Exception as e:
        logger.error("[ASR] 识别异常: %s", e)
        return ""
    finally:
        if wav_path and os.path.exists(wav_path):
            os.unlink(wav_path)
