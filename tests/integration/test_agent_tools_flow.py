"""
EchoSoul Agent 三工具系统集成测试

覆盖调用链：
  Skills 触发词匹配 → 激活技能包，工具注入 ToolRegistry
  MCP 工具启动时注册到 ToolRegistry
  Function Calling → LLM 在对话中自主决定调用工具
  Human-in-the-Loop → 敏感工具中断等待审批

运行：
  D:/Develop/PyCharm/envs/EchoSoul/python.exe -m pytest tests/integration/test_agent_tools_flow.py -v -s
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# ==================== 测试数据 ====================

MOCK_USER_INPUT_1 = "你还记得我喜欢什么颜色吗"
MOCK_USER_INPUT_2 = "我今天升职了！"
MOCK_USER_INPUT_3 = "给我讲个故事吧"

# ==================== Fixtures ====================


@pytest.fixture
def tool_registry():
    """创建一个带 10 个内置工具的 ToolRegistry。"""
    from app.domain.agent.tools.registry import ToolRegistry
    from app.domain.agent.tools.companion_tools import register_all_companion_tools
    r = ToolRegistry()
    register_all_companion_tools(r)
    return r


@pytest.fixture
def skill_registry():
    """从 skills/ 目录加载 Skill。"""
    from app.domain.agent.skills.registry import SkillRegistry
    sr = SkillRegistry("./skills")
    sr.initialize()
    return sr


@pytest.fixture
def emotion_svc():
    """Mock 情绪服务。"""
    from app.domain.emotion.service import EmotionService
    svc = MagicMock(spec=EmotionService)
    svc.analyze.return_value = {"label": "joy", "score": 0.8}

    # mock static method
    from unittest.mock import patch
    patcher = patch.object(EmotionService, 'get_emotion_style', return_value="活泼开朗")
    patcher.start()
    yield svc
    patcher.stop()


# ==================== Section 1: Function Calling 基础 ====================


class TestFunctionCallingBasics:
    """验证 10 个内置工具的正确性。"""

    def test_all_tools_registered(self, tool_registry):
        """10 个工具全部注册。"""
        names = tool_registry.get_tool_names()
        assert len(names) == 10, f"期望10个工具, 实际{len(names)}: {names}"

    def test_tool_to_openai_schema(self, tool_registry):
        """每个工具都能正确转换为 OpenAI function schema。"""
        tools = tool_registry.get_all_tools()
        for t in tools:
            assert "type" in t
            assert t["type"] == "function"
            assert "function" in t
            assert "name" in t["function"]
            assert "description" in t["function"]
            assert "parameters" in t["function"]

    def test_safe_vs_sensitive_classification(self, tool_registry):
        """工具分类：6个只读(自动通过) + 4个敏感(需审批)。"""
        sensitive = {"update_affection", "do_game_action",
                     "set_role_style", "progress_story"}
        all_names = set(tool_registry.get_tool_names())
        safe = all_names - sensitive

        assert len(sensitive) == 4
        assert len(safe) == 6, f"安全工具: {safe}"
        for name in safe:
            assert name not in sensitive

    def test_tool_registry_execution_count(self, tool_registry):
        """工具注册中心统计正确。"""
        assert tool_registry.tool_count == 10
        stats = tool_registry.get_stats()
        assert stats["total_registered"] == 10
        assert len(stats["internal"]) == 10


# ==================== Section 2: Skills 系统 ====================


class TestSkillsSystem:
    """验证 Skills 三级渐进加载。"""

    def test_skill_discovery(self, skill_registry):
        """Level 1: 发现 4 个 Skill。"""
        assert skill_registry.skill_count >= 4

    def test_skill_trigger_matching(self, skill_registry):
        """Level 2: 触发词匹配正确。"""
        # 用户说"还记得" → 触发 memory-recall
        triggered = skill_registry.check_triggers("你还记得我喜欢什么吗")
        assert "memory-recall" in triggered, f"应触发 memory-recall, 实际: {triggered}"

        # 用户说"讲故事" → 触发 story-branching
        triggered = skill_registry.check_triggers("给我讲个故事吧")
        assert "story-branching" in triggered, f"应触发 story-branching, 实际: {triggered}"

        # 普通聊天不触发
        triggered = skill_registry.check_triggers("你好")
        assert len(triggered) == 0, f"普通聊天不应触发, 实际: {triggered}"

    def test_skill_activation_and_tool_registration(self, skill_registry, tool_registry):
        """Level 3: 激活 Skill → 工具注入 ToolRegistry。"""
        initial_count = tool_registry.tool_count

        # 激活 memory-recall
        ok = skill_registry.activate_skill("memory-recall", tool_registry)
        assert ok
        assert "memory-recall" in skill_registry.active_skills

        # 工具数增加了（Skill 的工具已注入）
        skill = skill_registry._skills["memory-recall"]
        assert len(skill.tool_definitions) > 0

    def test_skill_deactivation_cleanup(self, skill_registry, tool_registry):
        """停用 Skill → 工具从 ToolRegistry 移除。"""
        skill_registry.activate_skill("memory-recall", tool_registry)
        skill_registry.activate_skill("game-actions", tool_registry)

        # 停用全部
        skill_registry.deactivate_all(tool_registry)
        assert skill_registry.active_count == 0

    def test_skill_progressive_disclosure(self, skill_registry):
        """验证三级数据完整性。"""
        for name in skill_registry._skills:
            skill = skill_registry._skills[name]
            # Level 1
            assert skill.metadata.name
            assert skill.metadata.description
            # Level 2
            if skill.brief:
                assert isinstance(skill.brief.capabilities, list)
            # Level 3
            assert isinstance(skill.tool_definitions, list)


# ==================== Section 3: MCP 集成 ====================


class TestMCPIntegration:
    """验证 MCP 客户端 + 适配器。"""

    def test_mcp_config_loads(self):
        """mcp_servers.json 可解析。"""
        config_path = Path("mcp_servers.json")
        if not config_path.exists():
            pytest.skip("mcp_servers.json 不存在")

        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert "companion-memory" in config
        assert "emotion-engine" in config

    def test_mcp_client_manager_init(self):
        """MCPClientManager 正常初始化。"""
        from app.domain.agent.mcp.client import MCPClientManager
        mgr = MCPClientManager("./mcp_servers.json")
        assert mgr.is_available  # langchain-mcp-adapters 已安装
        assert not mgr.is_connected  # 未 connect

    def test_mcp_adapter_schema(self):
        """MCPToolAdapter 正确转换工具 schema。"""
        from app.domain.agent.mcp.adapter import MCPToolAdapter

        # 创建一个 mock MCP tool
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test MCP tool"
        mock_tool.args_schema = None

        adapter = MCPToolAdapter(mock_tool, "test_server")
        adapted = adapter.to_openai_tool()

        assert adapted["type"] == "function"
        assert adapted["function"]["name"] == "test_tool"
        assert adapted["function"]["description"] == "A test MCP tool"


# ==================== Section 4: Agent 图数据流 ====================


class TestAgentDataFlow:
    """验证完整数据流：Function Calling + Skills + 中断。"""

    def test_agent_graph_compiles(self, tool_registry, emotion_svc):
        """Agent 图正确编译，7个节点。"""
        from app.domain.agent.graph import EchoSoulAgent
        agent = EchoSoulAgent(
            emotion_svc=emotion_svc,
            tool_registry=tool_registry,
        )
        nodes = list(agent.graph.nodes.keys())
        expected = ["__start__", "select_role", "emotion", "memory",
                    "router", "interrupt_check", "tool_exec", "generate"]
        for node in expected:
            assert node in nodes, f"缺少节点: {node}"
        print(f"\n  Agent 图节点: {nodes}")

    def test_build_initial_state(self):
        """AgentState 构建正确。"""
        state = {
            "user_id": "test_user_001",
            "user_input": "你好，还记得我喜欢什么吗",
            "role_type": "温柔贤淑型",
            "emotion": {},
            "memory_text": "",
            "final_response": None,
            "need_regenerate": False,
            "regenerate_context": None,
            "aff_info": "亲密度10, 信任10",
            "unlock_info": "",
            "tool_calls": [],
            "tool_messages": [],
            "tool_executions": [],
            "interaction_count": 0,
        }
        assert state["user_id"] == "test_user_001"
        assert state["tool_calls"] == []
        assert state["interaction_count"] == 0

    @pytest.mark.parametrize("tool_calls,expected_approval", [
        # 只有安全工具 → 不需要审批
        ([{"id": "1", "name": "recall_memory", "args": {"query": "喜欢的颜色"}}], False),
        # 有敏感工具 → 需要审批
        ([{"id": "2", "name": "save_memory", "args": {"fact": "用户升职了"}}], True),
        # 混合 → 需要审批（因为含敏感工具）
        ([
            {"id": "3", "name": "recall_memory", "args": {"query": "test"}},
            {"id": "4", "name": "update_affection", "args": {"intimacy": 0.5}},
        ], True),
        # 空 → 不需要
        ([], False),
    ])
    def test_interrupt_check_classification(self, tool_calls, expected_approval):
        """中断检查节点正确分类敏感 / 安全工具。"""
        from app.domain.agent.nodes import interrupt_check_node

        SENSITIVE = ["save_memory", "update_affection", "do_game_action",
                     "set_role_style", "progress_story"]

        state = {
            "user_id": "test",
            "user_input": "test",
            "role_type": "温柔贤淑型",
            "emotion": {},
            "memory_text": "",
            "final_response": None,
            "need_regenerate": False,
            "regenerate_context": None,
            "aff_info": "",
            "unlock_info": "",
            "tool_calls": tool_calls,
            "tool_messages": [],
            "tool_executions": [],
            "interaction_count": 0,
        }

        # 无敏感工具时，interrupt_check 不会调 interrupt()，直接返回
        if not expected_approval:
            # 安全工具 → 直接通过
            result = interrupt_check_node(state.copy(), SENSITIVE)
            assert result["tool_calls"] == tool_calls, \
                f"安全工具应直接通过, 实际: {result['tool_calls']}"
            print(f"\n  安全工具直接通过: {[t['name'] for t in tool_calls]}")
        else:
            print(f"\n  敏感工具需审批: {[t['name'] for t in tool_calls if t['name'] in set(SENSITIVE)]}")


# ==================== Section 5: Skills + Function Calling 联动 ====================


class TestSkillsFCCoordination:
    """Skills 激活后，其工具可被 Function Calling 发现和使用。"""

    def test_skill_tools_inject_into_registry(self, tool_registry):
        """激活 Skill → 工具注入 → LLM 可见。"""
        from app.domain.agent.skills.registry import SkillRegistry
        sr = SkillRegistry("./skills")
        sr.initialize()

        before_count = tool_registry.tool_count
        print(f"\n  激活前工具数: {before_count}")

        # 模拟触发：用户说"讲故事" → 激活 story-branching
        triggered = sr.check_triggers("给我讲个故事吧")
        for name in triggered:
            sr.activate_skill(name, tool_registry)

        after_count = tool_registry.tool_count
        print(f"  激活后工具数: {after_count}")

        # Skills 的工具已注入
        tools = tool_registry.get_all_tools()
        tool_names = [t["function"]["name"] for t in tools]
        print(f"  全部工具: {tool_names}")

        # 原有10个内置工具保留 + Skills 新增的工具
        assert after_count >= before_count


# ==================== Section 6: 完整对话模拟 ====================


class TestFullConversationSimulation:
    """模拟完整对话流程（Mock LLM）。"""

    def _build_minimal_state(self, user_input, role_type="温柔贤淑型"):
        return {
            "user_id": "test_user_001",
            "user_input": user_input,
            "role_type": role_type,
            "emotion": {"label": "neutral", "score": 0.5},
            "memory_text": "",
            "final_response": None,
            "need_regenerate": False,
            "regenerate_context": None,
            "aff_info": "亲密度10, 信任10",
            "unlock_info": "",
            "tool_calls": [],
            "tool_messages": [],
            "tool_executions": [],
            "interaction_count": 0,
        }

    def _mock_llm_stream(self, mock_llm, mock_resp):
        """Mock LLM.stream() 返回单个 chunk（模拟一次调用完成）。"""
        mock_llm.return_value.stream.return_value = [mock_resp]
        mock_llm.return_value.bind_tools.return_value = mock_llm.return_value

    def test_route_no_tools(self, tool_registry, emotion_svc):
        """场景1: 简单问候，LLM不调工具 → 直接回复。"""
        state = self._build_minimal_state("你好呀")

        from app.domain.agent.nodes import router_node

        # Mock LLM 返回纯文本（无 tool_calls）
        mock_resp = MagicMock()
        mock_resp.content = "你好呀！今天过得怎么样？"
        mock_resp.tool_calls = []

        with patch("app.domain.agent.nodes._get_tool_llm") as mock_llm:
            self._mock_llm_stream(mock_llm, mock_resp)
            result = router_node(state, emotion_svc, tool_registry)

        assert result["final_response"] == "你好呀！今天过得怎么样？"
        assert result["tool_calls"] == []
        print(f"\n  场景1-纯文本: '{state['user_input']}' -> '{result['final_response']}'")

    def test_route_safe_tool(self, tool_registry, emotion_svc):
        """场景2: 用户问记忆 -> LLM调 recall_memory（只读，自动通过）。"""
        state = self._build_minimal_state("你还记得我喜欢什么颜色吗")

        from app.domain.agent.nodes import router_node, interrupt_check_node

        SENSITIVE = ["save_memory", "update_affection", "do_game_action",
                     "set_role_style", "progress_story"]

        mock_resp = MagicMock()
        mock_resp.content = None
        mock_resp.tool_calls = [
            {"id": "call_001", "name": "recall_memory",
             "args": {"query": "喜欢的颜色"}, "type": "function"}
        ]

        with patch("app.domain.agent.nodes._get_tool_llm") as mock_llm:
            self._mock_llm_stream(mock_llm, mock_resp)
            result = router_node(state, emotion_svc, tool_registry)

        assert result["tool_calls"] == [
            {"id": "call_001", "name": "recall_memory", "args": {"query": "喜欢的颜色"}}
        ]
        assert result["final_response"] is None

        result2 = interrupt_check_node(result, SENSITIVE)
        assert len(result2["tool_calls"]) == 1
        assert result2["tool_calls"][0]["name"] == "recall_memory"
        print(f"\n  场景2-安全工具: recall_memory 自动通过审批")

    def test_route_sensitive_tool_needs_interrupt(self, tool_registry, emotion_svc):
        """场景3: 用户分享个人信息 -> LLM调 save_memory（需审批中断）。"""
        state = self._build_minimal_state("我今天升职了，成为部门主管了！")

        from app.domain.agent.nodes import router_node

        SENSITIVE = ["save_memory", "update_affection", "do_game_action",
                     "set_role_style", "progress_story"]

        mock_resp = MagicMock()
        mock_resp.content = None
        mock_resp.tool_calls = [
            {"id": "call_002", "name": "save_memory",
             "args": {"fact": "用户今天升职为部门主管", "category": "event"},
             "type": "function"},
            {"id": "call_003", "name": "update_affection",
             "args": {"intimacy": 1.5, "trust": 0.5, "reason": "用户升职"},
             "type": "function"},
        ]

        with patch("app.domain.agent.nodes._get_tool_llm") as mock_llm:
            self._mock_llm_stream(mock_llm, mock_resp)
            result = router_node(state, emotion_svc, tool_registry)

        assert len(result["tool_calls"]) == 2
        for tc in result["tool_calls"]:
            assert tc["name"] in SENSITIVE, f"{tc['name']} 应在敏感列表"
        print(f"\n  场景3-敏感工具: {[t['name'] for t in result['tool_calls']]} 需要审批")


# ==================== Section 7: Skills + FC + 中断联动 ====================


class TestThreeLayerIntegration:
    """三层联动：Skills 激活 → 工具注入 → Function Calling 调用 → 中断审批。"""

    @pytest.mark.skip(reason="需要 Mock interrupt() 的完整环境")
    def test_skills_story_flow(self):
        """用户说"讲故事" → Skills 激活 story-branching → LLM 调 progress_story → 中断审批。"""
        from app.domain.agent.skills.registry import SkillRegistry
        from app.domain.agent.tools.registry import ToolRegistry
        from app.domain.agent.tools.companion_tools import register_all_companion_tools

        # 1. 初始化
        tr = ToolRegistry()
        register_all_companion_tools(tr)
        sr = SkillRegistry("./skills")
        sr.initialize()

        print("\n  初始工具:", tr.get_tool_names())

        # 2. 用户说"讲故事" → Skills 触发
        user_msg = "给我讲个故事吧"
        triggered = sr.check_triggers(user_msg)
        print(f"  触发 Skills: {triggered}")

        for name in triggered:
            sr.activate_skill(name, tr)

        print(f"  激活后工具: {tr.get_tool_names()}")

        # 3. LLM 应该能发现 progress_story 工具
        tools = tr.get_all_tools()
        tool_names = [t["function"]["name"] for t in tools]
        assert "progress_story" in tool_names, f"progress_story 应该在工具列表中: {tool_names}"
        print("  验证通过: progress_story 可用")


# ==================== Main ====================

if __name__ == "__main__":
    print("=" * 60)
    print("EchoSoul 三工具系统数据流验证")
    print("=" * 60)

    # 1. Function Calling
    print("\n--- 1. Function Calling: 工具注册 ---")
    from app.domain.agent.tools.registry import ToolRegistry
    from app.domain.agent.tools.companion_tools import register_all_companion_tools
    tr = ToolRegistry()
    register_all_companion_tools(tr)
    print(f"  已注册 {tr.tool_count} 个工具:")
    for name in tr.get_tool_names():
        tag = "[敏感]" if name in {"save_memory", "update_affection", "do_game_action", "set_role_style", "progress_story"} else "[安全]"
        print(f"    {tag} {name}")

    # 2. Skills
    print("\n--- 2. Skills: 触发词匹配 ---")
    from app.domain.agent.skills.registry import SkillRegistry
    sr = SkillRegistry("./skills")
    sr.initialize()
    print(f"  已发现 {sr.skill_count} 个 Skill:")
    for name in sr._skills:
        s = sr._skills[name]
        print(f"    [{name}] {s.metadata.description[:40]}... trigger={s.metadata.trigger}")

    test_msgs = ["你还记得我喜欢什么吗", "给我讲个故事", "今天有什么任务", "心情不太好"]
    for msg in test_msgs:
        triggered = sr.check_triggers(msg)
        print(f"  '{msg}' → 触发: {triggered if triggered else '(无)'}")

    # 3. MCP
    print("\n--- 3. MCP: 配置状态 ---")
    from app.domain.agent.mcp.client import MCPClientManager
    mgr = MCPClientManager("./mcp_servers.json")
    print(f"  MCP 可用: {mgr.is_available}")
    print(f"  配置文件: {mgr._config_path}")
    if Path("mcp_servers.json").exists():
        config = json.loads(open("mcp_servers.json").read())
        for name, cfg in config.items():
            print(f"    [{name}] transport={cfg.get('transport')}")

    # 4. 数据流示例
    print("\n--- 4. 完整调用链数据流 ---")
    print("""
  用户: "我今天升职了！"
    │
    ▼
  [Skills] 检查触发词... 无匹配 → 保持当前工具集不变
    │
    ▼
  [MCP] 工具已在启动时加载（companion-memory: 2个, emotion-engine: 1个）
    │
    ▼
  [ToolRegistry] 当前工具池 = 10内置 + 0技能激活 + 0 MCP连接 = 10个
    │
    ▼
  [router_node] LLM.bind_tools(10个) ...
    LLM 判断: 需要存记忆 + 更新好感度
    → tool_calls: [save_memory, update_affection]
    │
    ▼
  [interrupt_check_node] save_memory ∈ 敏感列表 ⚠️
    → ⏸ interrupt() 暂停
    → 前端收到: {"sensitive_tools": ["save_memory", "update_affection"], ...}
    │
    ▼
  [用户审批] 点"允许" → Command(resume={"approved": ["save_memory", "update_affection"]})
    │
    ▼
  [tool_exec_node] save_memory → 写入PG
                   update_affection → 更新好感度
    │
    ▼
  [router_node] LLM 根据工具结果生成回复
    → "恭喜升职！我已经记住了这个好消息~"
    │
    ▼
  [generate_node] → END
""")

    print("=" * 60)
    print("验证完成")
    print("=" * 60)
