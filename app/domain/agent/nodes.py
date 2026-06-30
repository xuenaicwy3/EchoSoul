"""
LangGraph 状态图节点函数 —— 生产级 ReAct Agent + Human-in-the-Loop。

节点拓扑:
  select_role → emotion → memory → router
                                     ├─ (no tool_calls) → generate → END
                                     └─ (has tool_calls) → interrupt_check
                                                             ├─ (need approval) → ⏸ INTERRUPT
                                                             └─ (safe) → tool_exec
                                     tool_exec → router (loop)

中断机制（LangGraph interrupt）:
  interrupt_check_node 在检测到敏感工具调用时，调用 interrupt() 暂停图执行。
  状态通过 PostgresSaver 持久化，前端通过 SSE 收到中断事件。
  用户审批后通过 Command(resume=...) 恢复——interrupt() 返回审批结果，
  节点据此过滤 tool_calls（通过的执行，拒绝的注入错误消息）。
"""
import asyncio
import logging
import time
from typing import List, Optional

from langchain_core.messages import (
    HumanMessage, SystemMessage, AIMessage, ToolMessage,
)
from langgraph.types import interrupt, Command

from app.core.config import get_settings
from app.core.events import bus
from app.domain.agent.prompts import PromptFactory
from app.domain.emotion.service import EmotionService
from app.domain.memory.vector_service import VectorMemoryService
from app.domain.agent.tools.registry import ToolRegistry
from app.domain.roles.catalog import RoleCatalog
from app.models.schemas import AgentState

logger = logging.getLogger(__name__)

settings = get_settings()

# ---- LLM 实例（模块级复用） ----
_llm: Optional["BaseChatModel"] = None
_vector_memory_svc: Optional[VectorMemoryService] = None


def _get_llm() -> "BaseChatModel":
    global _llm
    if _llm is None:
        from app.infrastructure.llm import create_chat_model
        _llm = create_chat_model()
    return _llm


def _get_tool_llm():
    from app.infrastructure.llm import create_tool_llm
    return create_tool_llm()


def _get_vector_memory() -> VectorMemoryService:
    global _vector_memory_svc
    if _vector_memory_svc is None:
        _vector_memory_svc = VectorMemoryService(settings)
    return _vector_memory_svc


# ==================== Prefix 节点（保持不变） ====================


def select_role_node(state: AgentState, emotion_svc: EmotionService) -> AgentState:
    """角色选择节点：首次对话时分配默认角色。"""
    user_msg = state.get("user_input", "")
    if user_msg.startswith("[ROLE_SELECT]"):
        logger.info("[select_role] 角色已由 HTTP 层预设, role_type=%s", state.get("role_type"))
        return state
    if not state.get("role_type"):
        default = "温柔贤淑型"
        greeting = RoleCatalog.get_role(default).greeting
        logger.info("[select_role] 使用默认角色: %s", default)
        state["role_type"] = default
        state["final_response"] = greeting
    return state


def emotion_node(state: AgentState, emotion_svc: EmotionService) -> AgentState:
    """情绪分析节点。"""
    user_msg = state.get("user_input", "")
    if settings.TEST_MODE or not user_msg:
        state["emotion"] = {"label": "neutral", "score": 0.5}
        return state
    emotion = emotion_svc.analyze(user_msg)
    state["emotion"] = emotion
    return state


def memory_node(state: AgentState, emotion_svc: EmotionService) -> AgentState:
    """记忆检索节点。"""
    user_msg = state.get("user_input", "")
    if not user_msg or user_msg.startswith("[ROLE_SELECT]") or settings.TEST_MODE:
        return state

    user_id = state.get("user_id", "")
    role_type = state.get("role_type", "")
    if not user_id or not role_type:
        return state

    try:
        vms = _get_vector_memory()
        # smart_retrieve 内部完成嵌入+路由+检索，无需 ensure_loaded
        try:
            from app.chat_history import ChatHistoryManager
            rounds = asyncio.run(ChatHistoryManager().count_rounds(user_id, role_type))
        except Exception:
            rounds = 0

        layers = vms.smart_retrieve(user_id, role_type, user_msg, rounds)
        vector_text = VectorMemoryService.format_layers_for_prompt(layers)

        if not vector_text and rounds > 0:
            layers = vms.retrieve_all_layers(user_id, role_type, user_msg)
            vector_text = VectorMemoryService.format_layers_for_prompt(layers)

        if vector_text:
            existing = state.get("memory_text", "")
            state["memory_text"] = (existing + "\n\n" + vector_text) if existing else vector_text
    except Exception as e:
        logger.error("向量检索失败(已降级): %s", e)

    return state


# ==================== ReAct 节点 ====================


def router_node(state: AgentState, emotion_svc: EmotionService,
                tool_registry: ToolRegistry) -> AgentState:
    """ReAct 路由节点：LLM + 工具，决定调用工具 or 直接回复。

    首次进此节点时构建完整 messages（system_prompt + 用户输入）。
    后续迭代中 messages 已累积在 tool_messages 中，直接追加。

    Returns:
        state["tool_calls"] 非空 → 下一步 interrupt_check
        state["final_response"] 已设置 → 下一步 generate
    """
    if settings.TEST_MODE:
        state["final_response"] = "（测试模式）这是假回复。"
        state["tool_calls"] = []
        return state

    if state.get("final_response") and not state.get("need_regenerate"):
        state["tool_calls"] = []
        return state

    # 构建 messages
    role_type = state.get("role_type", "温柔贤淑型")
    emotion = state.get("emotion", {"label": "neutral", "score": 0.5})
    memory_text = state.get("memory_text", "")
    aff_info = state.get("aff_info", "亲密度10, 信任10")
    unlock_info = state.get("unlock_info", "")
    style = EmotionService.get_emotion_style(emotion["label"], emotion["score"])

    system_prompt = PromptFactory.system_prompt(role_type, style, memory_text, aff_info, unlock_info)

    # 追加工具调用提示（如果有可用工具）
    if tool_registry.tool_count > 0:
        system_prompt += (
            "\n\n你可以使用工具来更好地服务用户。"
            "当需要查询用户记忆、分析情绪、查看好感度或执行游戏/故事操作时，请调用相应工具。"
            "注意：涉及存储用户信息或修改数据的操作需要用户确认。"
        )

    messages = [SystemMessage(content=system_prompt)]

    # 追加 ReAct 对话历史
    tool_messages = state.get("tool_messages", [])
    for msg in tool_messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            kwargs = {"content": content}
            if msg.get("tool_calls"):
                kwargs["tool_calls"] = [
                    {"id": tc["id"], "name": tc["name"], "args": tc["args"], "type": "function"}
                    for tc in msg["tool_calls"]
                ]
            messages.append(AIMessage(**kwargs))
        elif role == "tool":
            messages.append(ToolMessage(
                content=content,
                tool_call_id=msg.get("tool_call_id", ""),
                name=msg.get("name", ""),
            ))

    # 首次进入 ReAct 时追加用户输入
    if not tool_messages:
        user_input = state["user_input"]
        if state.get("need_regenerate") and state.get("regenerate_context"):
            ctx = state["regenerate_context"]
            user_input = PromptFactory.regenerate(ctx["user_msg"], ctx["ai_msg"])
        messages.append(HumanMessage(content=user_input))

    # LLM + tools
    all_tools = tool_registry.get_all_tools()
    llm = _get_tool_llm()
    if all_tools:
        llm = llm.bind_tools(all_tools)

    # 流式调用 LLM，逐 token 产出，累积为完整 AIMessage
    # stream() 使上层 graph.astream_events() 能捕获 on_chat_model_stream 事件
    from langchain_core.messages import AIMessageChunk
    resp: AIMessageChunk | None = None
    for chunk in llm.stream(messages):
        resp = chunk if resp is None else resp + chunk

    # 判断结果
    if resp and hasattr(resp, "tool_calls") and resp.tool_calls:
        logger.info("[router] LLM 请求 %d 个工具: %s",
                    len(resp.tool_calls),
                    [tc["name"] for tc in resp.tool_calls])

        state.setdefault("tool_messages", []).append({
            "role": "assistant",
            "content": resp.content or "",
            "tool_calls": [
                {"id": tc["id"], "name": tc["name"], "args": tc["args"]}
                for tc in resp.tool_calls
            ],
        })

        state["tool_calls"] = [
            {"id": tc["id"], "name": tc["name"], "args": tc["args"]}
            for tc in resp.tool_calls
        ]
    else:
        state["final_response"] = resp.content
        state["tool_calls"] = []

    return state


# ==================== 中断审批节点（Human-in-the-Loop 核心） ====================


def interrupt_check_node(state: AgentState, sensitive_tools: List[str]) -> AgentState:
    """人工审批门控节点。

    检查 router 产出的 tool_calls，将敏感工具分离出来请求用户审批。
    安全工具直接放行，敏感工具暂停等待人工决策。

    中断流程:
      1. 检测到敏感工具 → 调用 interrupt() 暂停图执行
      2. 前端通过 SSE 收到中断事件（含工具名/参数/问题描述）
      3. 用户 approve/reject → 前端发送 Command(resume={...})
      4. interrupt() 返回审批结果 → 过滤 tool_calls
      5. 审批通过的工具进入 tool_exec，拒绝的注入错误消息

    正式场景:
      AI 想调 save_memory 存储"用户升职了" → ⏸ 暂停，"AI 想记住这件事，允许吗？"
      AI 想调 update_affection(+5) → ⏸ 暂停，"AI 想提升好感度，允许吗？"
      AI 想调 do_game_action 领取奖励 → ⏸ 暂停
      AI 想调 recall_memory（只读）→ ▶️ 直接通过
    """
    tool_calls = state.get("tool_calls", [])
    if not tool_calls:
        return state

    # 分类：安全工具 vs 敏感工具
    safe_calls = []
    sensitive_calls = []

    for tc in tool_calls:
        if tc["name"] in sensitive_tools:
            sensitive_calls.append(tc)
        else:
            safe_calls.append(tc)

    # 无敏感工具 → 直接放行
    if not sensitive_calls:
        logger.info("[interrupt_check] 全部安全工具 (%d)，直接放行", len(safe_calls))
        return state

    # 有敏感工具 → 中断等审批
    logger.info(
        "[interrupt_check] 敏感工具 %d 个 (%s)，暂停等待审批",
        len(sensitive_calls),
        [tc["name"] for tc in sensitive_calls],
    )

    # 构建中断信息（发给前端展示）
    interrupt_payload = {
        "type": "tool_approval",
        "sensitive_tools": [
            {
                "id": tc["id"],
                "name": tc["name"],
                "args": tc["args"],
                "description": _describe_tool_action(tc),
            }
            for tc in sensitive_calls
        ],
        "safe_tools": [
            {"id": tc["id"], "name": tc["name"]}
            for tc in safe_calls
        ],
        "message": _build_approval_message(sensitive_calls),
    }

    # ⏸️ 暂停！状态写入 checkpointer（PostgresSaver），等待 Command(resume=...)
    approval_result = interrupt(interrupt_payload)

    # ▶️ 恢复！approval_result = Command(resume=...) 传入的值
    logger.info("[interrupt_check] 审批结果: %s", approval_result)

    # 处理审批结果
    approved_names = set(approval_result.get("approved", [])) if approval_result else set()
    rejected_names = set(approval_result.get("rejected", [])) if approval_result else set()

    # 通过的工具 + 拒绝的工具注入错误消息
    approved_calls = []
    for tc in sensitive_calls:
        if tc["name"] in approved_names:
            approved_calls.append(tc)
        else:
            # 拒绝的工具：注入 ToolMessage 告知 LLM 操作被拒绝
            rejection_msg = approval_result.get("rejection_reason", "用户拒绝了此操作。")
            state.setdefault("tool_messages", []).append({
                "role": "tool",
                "content": f"[被拒绝] {tc['name']}: {rejection_msg}",
                "tool_call_id": tc["id"],
                "name": tc["name"],
            })
            logger.info("[interrupt_check] 工具 '%s' 被用户拒绝", tc["name"])

    # 合并：安全工具 + 审批通过的工具
    state["tool_calls"] = safe_calls + approved_calls

    if not state["tool_calls"]:
        logger.info("[interrupt_check] 无待执行工具（全部被拒绝或安全工具已合并）")

    # 记录审批操作
    state.setdefault("tool_executions", []).append({
        "tool_name": "interrupt_check",
        "success": True,
        "result_preview": f"审批: 通过{len(approved_calls)}个, 拒绝{len(rejected_names)}个",
    })

    return state


def _describe_tool_action(tc: dict) -> str:
    """生成人类可读的工具操作描述。"""
    name = tc["name"]
    args = tc.get("args", {})
    descriptions = {
        "save_memory": f"存储记忆: {args.get('fact', '')}",
        "update_affection": f"更新好感度: intimacy={args.get('intimacy', 0)}, trust={args.get('trust', 0)}, fun={args.get('fun', 0)}, growth={args.get('growth', 0)}",
        "do_game_action": f"执行游戏动作: {args.get('action', '')}",
        "set_role_style": f"切换角色: {args.get('role_name', '')}",
        "progress_story": f"推进故事: {args.get('action', '')}",
    }
    return descriptions.get(name, f"执行 {name}: {args}")


def _build_approval_message(sensitive_calls: list) -> str:
    """构建给用户的审批提示。"""
    if len(sensitive_calls) == 1:
        tc = sensitive_calls[0]
        return f"AI 想执行「{tc['name']}」操作，是否允许？"
    return f"AI 想执行 {len(sensitive_calls)} 个操作（{', '.join(tc['name'] for tc in sensitive_calls)}），是否允许？"


# ==================== 工具执行节点 ====================


def tool_exec_node(state: AgentState, tool_registry: ToolRegistry) -> AgentState:
    """工具执行节点：执行 tool_calls 中通过审批的工具。

    每条 tool_call 执行后写入 tool_messages 供 router 下一轮读取。
    递增 interaction_count 控制循环上限。
    """
    tool_calls = state.get("tool_calls", [])
    if not tool_calls:
        return state

    context = _build_tool_context(state)
    executions = []

    for tc in tool_calls:
        tool_name = tc["name"]
        tool_args = dict(tc.get("args", {}))
        tool_args["_tool_call_id"] = tc["id"]

        start = time.monotonic()
        try:
            # Celery 内 asyncio.run() 可能已存在 event loop，兼容处理
            try:
                result = asyncio.run(tool_registry.execute(tool_name, tool_args, context))
            except RuntimeError:
                loop = asyncio.get_event_loop()
                result = loop.run_until_complete(
                    tool_registry.execute(tool_name, tool_args, context)
                )
            duration_ms = int((time.monotonic() - start) * 1000)
        except Exception as e:
            result = None
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error("[tool_exec] '%s' 异常: %s", tool_name, e)

        if result:
            executions.append({
                "tool_name": tool_name,
                "success": result.success,
                "result_preview": str(result.result)[:200] if result.result else None,
                "error": result.error,
                "duration_ms": duration_ms,
            })

            tool_content = str(result.result) if result.success else f"Error: {result.error}"
            state.setdefault("tool_messages", []).append({
                "role": "tool",
                "content": tool_content,
                "tool_call_id": tc["id"],
                "name": tool_name,
            })

            # 发射事件（Celery 无 event loop 时静默跳过）
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(bus.emit("tool.called", {
                        "tool_name": tool_name,
                        "success": result.success,
                        "duration_ms": duration_ms,
                        "user_id": context.get("user_id", ""),
                    }))
            except RuntimeError:
                pass
        else:
            state.setdefault("tool_messages", []).append({
                "role": "tool",
                "content": "Error: 工具执行异常",
                "tool_call_id": tc["id"],
                "name": tool_name,
            })

    state["tool_calls"] = []
    state["interaction_count"] = state.get("interaction_count", 0) + 1
    state["tool_executions"] = state.get("tool_executions", []) + executions

    logger.info("[tool_exec] 完成 %d 个工具，迭代 #%d",
                len(tool_calls), state["interaction_count"])
    return state


# ==================== 终止节点 ====================


def generate_node(state: AgentState, emotion_svc: EmotionService) -> AgentState:
    """终止节点：确保 final_response 有效。

    正常流程中 router_node 在无 tool_calls 时已设置 final_response，
    此节点处理兜底情况。
    """
    if settings.TEST_MODE:
        state["final_response"] = "（测试模式）这是假回复。"
        state["need_regenerate"] = False
        return state

    if not state.get("final_response"):
        logger.warning("[generate] final_response 为空，兜底生成")
        llm = _get_llm()
        role_type = state.get("role_type", "温柔贤淑型")
        user_input = state.get("user_input", "")
        messages = [
            SystemMessage(content=f"你是{role_type}的虚拟伴侣，请简短回复用户。"),
            HumanMessage(content=user_input),
        ]
        resp = llm.invoke(messages)
        state["final_response"] = resp.content

    state["need_regenerate"] = False
    return state


# ==================== 条件边辅助函数 ====================


def _has_tool_calls(state: AgentState) -> bool:
    """router → interrupt_check 或 router → generate"""
    tc = state.get("tool_calls", [])
    iterations = state.get("interaction_count", 0)
    if iterations >= settings.MAX_TOOL_ITERATIONS:
        logger.info("[router] 达到最大迭代 %d，强制终止", settings.MAX_TOOL_ITERATIONS)
        return False
    return bool(tc)


def _needs_approval(state: AgentState) -> bool:
    """interrupt_check 后是否有工具需要执行。

    True  → 进入 tool_exec（含审批通过的工具 + 安全工具）
    False → 进入 generate（全部被拒且无安全工具）
    """
    return bool(state.get("tool_calls", []))


def _build_tool_context(state: AgentState) -> dict:
    return {
        "user_id": state.get("user_id", ""),
        "role_type": state.get("role_type", ""),
        "emotion": state.get("emotion", {}),
        "memory_text": state.get("memory_text", ""),
        "aff_info": state.get("aff_info", ""),
        "unlock_info": state.get("unlock_info", ""),
        "user_input": state.get("user_input", ""),
    }
