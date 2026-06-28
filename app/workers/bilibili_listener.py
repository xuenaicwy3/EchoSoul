"""
B站 AI 虚拟主播 — 最简版弹幕监听。

监听直播间弹幕 → 调用 EchoSoul LLM → TTS → 弹幕回直播间 + VRM 说话。

启动方式:
    python -m app.workers.bilibili_listener --room-id 你的房间号

依赖:
    pip install bilibili-api-python
"""
import asyncio
import logging
import time
from typing import Optional

from bilibili_api import live, Credential

logger = logging.getLogger(__name__)

# ==================== 配置 ====================

# B站直播间房间号（默认值，启动时 --room-id 覆盖）
ROOM_ID = 27674073

# 弹幕缓存队列最大长度
DANMAKU_QUEUE_SIZE = 20

# AI 回复最大长度（字符）
MAX_REPLY_LEN = 60

# 两次回复最小间隔（秒）— 防止刷屏
MIN_REPLY_INTERVAL = 5


class BilibiliAIStreamer:
    """B站 AI 虚拟主播核心类。"""

    def __init__(self, room_id: int):
        self.room_id = room_id
        self.room = live.LiveRoom(room_display_id=room_id)
        self.danmaku_queue: list[dict] = []
        self.last_reply_time = 0.0
        self.running = False

    async def send_reply(self, text: str) -> None:
        """AI 回复弹幕发回直播间。"""
        now = time.time()
        if now - self.last_reply_time < MIN_REPLY_INTERVAL:
            return  # 间隔太短，跳过
        self.last_reply_time = now

        # 截断过长文本
        if len(text) > MAX_REPLY_LEN:
            text = text[:MAX_REPLY_LEN - 3] + "..."

        try:
            await self.room.send_danmaku(live.Danmaku(text))
            logger.info("[AI主播] 弹幕回复: %s", text[:40])
        except Exception as e:
            logger.error("[AI主播] 弹幕发送失败: %s", e)

    async def generate_reply(self, user_text: str, username: str) -> Optional[str]:
        """调用 EchoSoul LLM 生成回复。"""
        try:
            from app.core.config import get_settings
            from langchain.chat_models import init_chat_model
            from langchain_core.messages import SystemMessage, HumanMessage

            settings = get_settings()
            llm = init_chat_model(
                model=settings.LLM_MODEL,
                model_provider="openai",
                temperature=0.9,
                max_tokens=80,
                api_key=settings.DASHSCOPE_API_KEY,
                base_url=settings.DASHSCOPE_BASE_URL,
            )

            prompt = (
                "你是一个正在B站直播的AI虚拟主播，名字叫小樱，性格活泼可爱。"
                f"有一个叫'{username}'的观众发了一条弹幕。"
                "请用简短口语化的方式回复（15字以内），不要用括号描述动作。"
            )
            messages = [
                SystemMessage(content=prompt),
                HumanMessage(content=f"弹幕内容：{user_text}"),
            ]
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, llm.invoke, messages)
            return resp.content.strip()
        except Exception as e:
            logger.error("[AI主播] LLM调用失败: %s", e)
            return None

    async def handle_danmaku(self, event: dict) -> None:
        """处理一条弹幕。"""
        data = event.get("data", {})
        info = data.get("info", [])
        if len(info) < 2:
            return

        text = str(info[1])  # 弹幕内容
        user = str(info[2][1]) if len(info) > 2 and info[2] else "观众"  # 用户名

        # 过滤空弹幕和纯表情
        if not text.strip() or len(text) < 2:
            return

        logger.info("[AI主播] 弹幕: %s: %s", user, text[:30])

        # 生成 AI 回复
        reply = await self.generate_reply(text, user)
        if reply:
            await self.send_reply(reply)

    async def start(self) -> None:
        """启动弹幕监听。"""
        self.running = True
        logger.info("[AI主播] 开始监听直播间 %s", self.room_id)

        monitor = live.LiveDanmaku(self.room_id)

        @monitor.on("DANMU_MSG")
        async def on_danmaku(event):
            if self.running:
                await self.handle_danmaku(event)

        @monitor.on("INTERACT_WORD")
        async def on_enter(event):
            data = event.get("data", {})
            username = data.get("uname", "未知")
            logger.info("[AI主播] %s 进入了直播间", username)

        await monitor.connect()

    def stop(self) -> None:
        self.running = False
        logger.info("[AI主播] 已停止")


# ==================== 启动入口 ====================

async def main():
    import argparse
    from app.core.logging_config import setup_logging
    setup_logging("INFO")

    parser = argparse.ArgumentParser(description="B站 AI 虚拟主播")
    parser.add_argument("--room-id", type=int, default=ROOM_ID, help="直播间房间号")
    args = parser.parse_args()

    streamer = BilibiliAIStreamer(room_id=args.room_id)
    try:
        await streamer.start()
    except KeyboardInterrupt:
        streamer.stop()


if __name__ == "__main__":
    asyncio.run(main())
