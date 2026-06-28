"""
B站直播间操作：发弹幕、禁言、查询信息。
"""
import logging
from bilibili_api import live, Credential

logger = logging.getLogger(__name__)


class LiveRoom:
    """B站直播间操作封装。"""

    def __init__(self, room_id: int, credential: Credential | None = None):
        self.room = live.LiveRoom(room_display_id=room_id, credential=credential)

    async def send_danmaku(self, text: str) -> bool:
        """发送弹幕到直播间。"""
        try:
            await self.room.send_danmaku(live.Danmaku(text))
            logger.info("[Bili] 弹幕已发送: %s", text[:40])
            return True
        except Exception as e:
            logger.error("[Bili] 弹幕发送失败: %s", e)
            return False

    async def get_room_info(self) -> dict:
        """获取直播间信息。"""
        try:
            info = await self.room.get_room_info()
            return info
        except Exception as e:
            logger.error("[Bili] 获取房间信息失败: %s", e)
            return {}
