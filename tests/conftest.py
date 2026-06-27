"""
pytest 全局配置和共享 fixtures。
"""
import asyncio
import sys
from pathlib import Path

import pytest

# 确保项目根目录在 Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import Settings  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    """创建 session 级别的事件循环。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_settings() -> Settings:
    """提供测试用 Settings 实例（TEST_MODE=True）。"""
    return Settings(
        DASHSCOPE_API_KEY="test-key",
        TEST_MODE=True,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        REDIS_URL="redis://localhost:6379/0",
        SECRET_KEY="test-secret-key",
    )


@pytest.fixture
def event_bus():
    """提供干净的 EventBus 实例。"""
    from app.core.events import EventBus
    bus = EventBus()
    yield bus
    bus.clear()
