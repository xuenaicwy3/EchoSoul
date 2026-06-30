"""
MCP (Model Context Protocol) 集成层。

通过 langchain-mcp-adapters 连接外部 MCP 服务器，
将其工具适配为内部 BaseTool 格式后注册到 ToolRegistry。

架构:
  MCP Servers (stdio/SSE/Streamable HTTP)
       │
       ▼
  MultiServerMCPClient (langchain-mcp-adapters)
       │
       ▼
  MCPToolAdapter (MCP 工具 → BaseTool)
       │
       ▼
  ToolRegistry
"""
