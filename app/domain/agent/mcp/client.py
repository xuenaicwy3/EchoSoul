"""
MCP 客户端管理器 —— 管理 MCP 服务器连接生命周期。

在整个 FastAPI lifespan 中保持连接，
Agent 执行时通过 get_mcp_tools() 获取当前可用的 MCP 工具。
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# langchain-mcp-adapters 为可选依赖
try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    MultiServerMCPClient = None  # type: ignore


class MCPClientManager:
    """管理 MCP 客户端生命周期。

    用法:
      manager = MCPClientManager("./mcp_servers.json")
      await manager.connect()           # lifespan startup
      tools = manager.get_flat_tools()  # agent 初始化
      await manager.disconnect()        # lifespan shutdown
    """

    def __init__(self, config_path: str = "./mcp_servers.json") -> None:
        self._config_path = Path(config_path)
        self._client: Optional["MultiServerMCPClient"] = None
        self._connected: bool = False

        if not _MCP_AVAILABLE:
            logger.warning(
                "langchain-mcp-adapters 未安装，MCP 功能不可用。"
                "安装: pip install langchain-mcp-adapters"
            )

    @property
    def client(self) -> Optional["MultiServerMCPClient"]:
        return self._client

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_available(self) -> bool:
        return _MCP_AVAILABLE

    # ---- 连接生命周期 ----

    async def connect(self) -> bool:
        """连接所有配置的 MCP 服务器。

        Returns:
            True 若至少连接了一个服务器。
        """
        if not _MCP_AVAILABLE:
            logger.warning("MCP 不可用，跳过连接")
            return False

        if not self._config_path.exists():
            logger.info("MCP 配置文件不存在: %s，跳过 MCP", self._config_path)
            return False

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("MCP 配置文件读取失败: %s", e)
            return False

        if not config:
            logger.info("MCP 配置为空，跳过连接")
            return False

        self._client = MultiServerMCPClient()

        for server_name, server_config in config.items():
            transport = server_config.get("transport", "stdio")

            try:
                if transport == "stdio":
                    self._client.add_server(
                        name=server_name,
                        transport="stdio",
                        command=server_config.get("command", "python"),
                        args=server_config.get("args", []),
                        env=server_config.get("env"),
                    )
                elif transport in ("sse", "streamable_http", "streamable-http"):
                    url = server_config.get("url", "")
                    if not url:
                        logger.error("MCP 服务器 '%s' 缺少 url", server_name)
                        continue
                    self._client.add_server(
                        name=server_name,
                        transport=transport,
                        url=url,
                        headers=server_config.get("headers"),
                    )
                else:
                    logger.error("不支持的 MCP 传输方式: %s (server=%s)", transport, server_name)
                    continue

                logger.info("MCP 服务器已配置: %s (transport=%s)", server_name, transport)

            except Exception as e:
                logger.error("MCP 服务器 '%s' 配置失败: %s", server_name, e)

        # 建立所有连接
        try:
            await self._client.__aenter__()
            self._connected = True
            logger.info("MCP 客户端已连接，服务器数=%d", len(config))
            return True
        except Exception as e:
            logger.error("MCP 连接失败: %s", e)
            self._client = None
            return False

    async def disconnect(self) -> None:
        """断开所有 MCP 连接。"""
        if self._client and self._connected:
            try:
                await self._client.__aexit__(None, None, None)
                logger.info("MCP 客户端已断开")
            except Exception as e:
                logger.error("MCP 断开异常: %s", e)
            finally:
                self._connected = False
                self._client = None

    # ---- 工具获取 ----

    def get_mcp_tools(self) -> Dict[str, list]:
        """获取所有 MCP 服务器的工具（原始格式），keyed by server name。

        仅在 connected 状态下有效。
        """
        if not self._client or not self._connected:
            return {}

        try:
            return self._client.get_tools()
        except Exception as e:
            logger.error("获取 MCP 工具失败: %s", e)
            return {}

    def get_flat_tools(self, prefix: str = "mcp_") -> list:
        """获取扁平化的 MCP 工具列表（带命名空间前缀）。

        返回的每个工具对象是 langchain BaseTool 兼容格式，
        可直接通过 MCPToolAdapter 注册到 ToolRegistry。

        Args:
            prefix: MCP 工具名前缀，用于区分来源（如 "mcp_memory_recall"）。
        """
        if not self._client or not self._connected:
            return []

        tools = []
        for server_name, server_tools in self.get_mcp_tools().items():
            for tool in server_tools:
                # 添加命名空间前缀防止冲突
                tool.name = f"{prefix}{server_name}_{tool.name}"
                tools.append(tool)

        logger.debug("MCP 扁平化工具: %d 个", len(tools))
        return tools
