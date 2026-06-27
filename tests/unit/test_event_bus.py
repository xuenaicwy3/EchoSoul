"""
EventBus 单元测试。
"""
import asyncio
import pytest

from app.core.events import EventBus


class TestEventBus:
    """内部事件总线测试。"""

    def test_register_and_emit(self):
        """处理器注册后，事件发射应触发处理器。"""
        bus = EventBus()
        received = []

        @bus.on("test.event")
        async def handler(data):
            received.append(data)

        asyncio.run(bus.emit("test.event", {"msg": "hello"}))
        assert len(received) == 1
        assert received[0]["msg"] == "hello"

    def test_multiple_handlers(self):
        """多个处理器应全部被调用。"""
        bus = EventBus()
        results = []

        @bus.on("multi")
        async def h1(data):
            results.append("a")

        @bus.on("multi")
        async def h2(data):
            results.append("b")

        asyncio.run(bus.emit("multi", {}))
        assert sorted(results) == ["a", "b"]

    def test_handler_exception_does_not_block_others(self):
        """一个处理器抛异常不应阻止其他处理器。"""
        bus = EventBus()
        ok_called = False

        @bus.on("safe")
        async def bad_handler(data):
            raise RuntimeError("oops")

        @bus.on("safe")
        async def good_handler(data):
            nonlocal ok_called
            ok_called = True

        asyncio.run(bus.emit("safe", {}))
        assert ok_called is True

    def test_no_handlers_no_error(self):
        """无处理器的空事件发射不应报错。"""
        bus = EventBus()
        asyncio.run(bus.emit("no.handlers", {}))

    def test_clear_removes_all(self):
        """clear() 后事件不应有处理器。"""
        bus = EventBus()

        @bus.on("x")
        async def h(data):
            pass

        bus.clear()
        assert bus.handler_count == {}

    def test_handler_count(self):
        """handler_count 应正确反映注册数。"""
        bus = EventBus()

        @bus.on("event.a")
        async def h1(data):
            pass

        @bus.on("event.a")
        async def h2(data):
            pass

        @bus.on("event.b")
        async def h3(data):
            pass

        assert bus.handler_count == {"event.a": 2, "event.b": 1}
        bus.clear()
