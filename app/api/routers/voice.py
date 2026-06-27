"""
语音对话 WebSocket 端点。

借鉴 Open-LLM-VTuber 的消息协议：
  Client → Server: mic-audio-start / mic-audio-data / mic-audio-end / interrupt
  Server → Client: asr-result / asr-final / audio-chunk / speech-end
"""
import asyncio
import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import decode_access_token
from app.domain.voice.voice_pipeline import VoicePipeline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])


@router.websocket("/ws/voice/{user_id}")
async def voice_websocket(websocket: WebSocket, user_id: str):
    """语音对话 WebSocket 端点。"""
    # 从首个消息中提取 token 验证
    await websocket.accept()
    first_msg = await websocket.receive_text()
    try:
        data = json.loads(first_msg)
        token = data.get("token", "")
    except json.JSONDecodeError:
        token = first_msg  # 兼容纯 token 字符串
    uid = decode_access_token(token)
    if not uid or uid != user_id:
        await websocket.close(code=4001, reason="Auth failed")
        return

    logger.info("[Voice WS] 连接: user=%s", user_id[:8])
    pipeline = VoicePipeline()
    audio_chunks: list[bytes] = []
    task: asyncio.Task | None = None
    role_type = "温柔贤淑型"  # 默认，后续从 token/query 获取

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "mic-audio-start":
                audio_chunks = []
                logger.debug("[Voice] 开始接收音频")
                # 打断正在播放的回复
                if task and not task.done():
                    pipeline.interrupt()

            elif msg_type == "mic-audio-data":
                try:
                    data = base64.b64decode(msg["data"])
                    audio_chunks.append(data)
                except Exception:
                    pass

            elif msg_type == "mic-audio-end":
                logger.info("[Voice] 音频接收完成: %d chunks", len(audio_chunks))
                # 启动语音处理管线（asyncio Task，不阻塞消息循环）
                task = asyncio.create_task(
                    _run_pipeline(websocket, pipeline, audio_chunks, user_id, role_type)
                )

            elif msg_type == "interrupt":
                pipeline.interrupt()
                if task and not task.done():
                    task.cancel()
                logger.debug("[Voice] 打断")

            elif msg_type == "set-role":
                role_type = msg.get("role_type", role_type)

    except WebSocketDisconnect:
        logger.info("[Voice WS] 断开: user=%s", user_id[:8])
    finally:
        pipeline.interrupt()
        if task and not task.done():
            task.cancel()


async def _run_pipeline(
    ws: WebSocket,
    pipeline: VoicePipeline,
    audio_chunks: list[bytes],
    user_id: str,
    role_type: str,
) -> None:
    """执行语音管线，将产出的消息逐个推送回前端。"""
    try:
        async for msg in pipeline.process(audio_chunks, user_id, role_type):
            await ws.send_text(json.dumps(msg, ensure_ascii=False))
    except asyncio.CancelledError:
        logger.debug("[Voice] 管线被取消")
    except Exception as e:
        logger.error("[Voice] 管线异常: %s", e)
        try:
            await ws.send_text(json.dumps({"type": "speech-end"}))
        except Exception:
            pass
