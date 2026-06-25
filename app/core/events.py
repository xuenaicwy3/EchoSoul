"""
轻量级进程内事件总线。

零外部依赖，用于解耦服务间通信。
典型用法：
    # 发射
    await bus.emit("chat.completed", {"user_id": "u1", "reply": "..."})

    # 订阅
    @bus.on("chat.completed")
    async def handle(event): ...
"""
import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine, Dict, List

logger = logging.getLogger(__name__)

Handler = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]


class EventBus:
    """进程内事件总线，支持多对多发布/订阅"""

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Handler]] = defaultdict(list)

    def on(self, event: str):
        """装饰器：注册事件处理器。

        @bus.on("chat.completed")
        async def handle_store_history(event): ...
        """
        def decorator(fn: Handler) -> Handler:
            self._handlers[event].append(fn)
            logger.debug("事件 '%s' 注册处理器: %s", event, fn.__name__)
            return fn
        return decorator

    async def emit(self, event: str, data: Dict[str, Any]) -> None:
        """发射事件，并发执行所有注册的处理器。

        单个处理器异常不会影响其他处理器。
        """
        handlers = self._handlers.get(event, [])
        if not handlers:
            return

        logger.debug("事件 '%s' 触发，处理器数=%d", event, len(handlers))
        tasks = []
        for handler in handlers:
            tasks.append(self._safe_invoke(handler, event, data))

        await asyncio.gather(*tasks)

    async def _safe_invoke(self, handler: Handler, event: str, data: Dict[str, Any]) -> None:
        try:
            await handler(data)
        except Exception:
            logger.exception(
                "事件 '%s' 处理器 '%s' 异常",
                event, getattr(handler, "__name__", handler)
            )

    def clear(self) -> None:
        """清空所有注册的处理器（主要用于测试）。"""
        self._handlers.clear()

    @property
    def handler_count(self) -> Dict[str, int]:
        """返回各事件的处理器数量（用于调试）。"""
        return {event: len(hs) for event, hs in self._handlers.items()}


# 全局单例 — 所有模块共享此实例
bus = EventBus()
