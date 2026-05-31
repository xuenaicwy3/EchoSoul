"""
核心对话智能体
依赖注入 EmotionAnalyzer, MemoryManager, AffectionManager
使用 LangGraph 构建 4 节点流水线：角色选择 → 情感分析 → 记忆检索 → 生成回复
"""
import logging
from typing import Optional, cast, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.chat_models import init_chat_model
from app.config import Settings
# from app.interfaces import EmotionAnalyzer, MemoryManager, AffectionManager
from app.roles import RoleCatalog
from app.prompts import PromptFactory
from app.emotions import EmotionService   # 用于调用静态方法 get_emotion_style
from app.memory import MemoryService
from app.affection import AffectionService
from app.models.schemas import AgentState  # 新增导入
from langchain_core.runnables import RunnableConfig
logger = logging.getLogger(__name__)



class EchoSoulAgent:
    """
    心流虚拟伴侣智能体
    封装了对话处理的完整生命周期
    """

    def __init__(
        self,
        settings: Settings,
        emotion_svc: EmotionService,
        memory_svc: MemoryService,
        affection_svc: AffectionService,
    ):
        self.settings = settings
        # 主对话 LLM
        self.llm = init_chat_model(
            model=settings.LLM_MODEL,
            model_provider="openai",
            temperature=0.8,
            max_tokens=512,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
        )
        self.emotion_svc = emotion_svc
        self.memory_svc = memory_svc
        self.affection_svc = affection_svc
        self.checkpointer = MemorySaver()   # 多轮对话状态持久化
        self.graph = self._build_graph()
        logger.info("EchoSoulAgent 初始化完成，对话模型=%s", settings.LLM_MODEL)
        logger.info("emotion_svc: %s", self.emotion_svc.analyze("纯欲美女"))
        logger.info("总记忆数: %s", self.memory_svc.collection.count())
        #logger.info(f"示例数据: {self.memory_svc.collection.peek(5)}")
        #logger.info("vec数量: %s", self.memory_svc.embeddings.embed_query("测试"))

    # -------------------- 节点函数（参数和返回均已适配 AgentState） --------------------
    def _select_role_node(self, state: AgentState) -> AgentState:
        """节点1：识别并设置角色，返回开场白"""
        user_msg = state.get("user_input", "")
        print("[user_msg] 输入: %s", user_msg[:50])

        # 如果消息是 [ROLE_SELECT]，说明角色和开场白已由 HTTP 层预设，直接透传
        if user_msg.startswith("[ROLE_SELECT]"):
            logger.info("[select_role] 角色已由 HTTP 层预设，当前 role_type = %s", state.get("role_type"))
            return state

        logger.info("[select_role] 当前 role_type = %s", state.get("role_type"))
        logger.info("当前 state keys: %s", list(state.keys()))
        logger.info("[select_role] 用户输入: %s", user_msg[:50])

        # 如果当前没有角色，赋予默认角色（温柔贤淑型）并返回开场白
        if not state.get("role_type"):
            default = "温柔贤淑型"
            greeting = RoleCatalog.get_role(default).greeting
            logger.info("[select_role] 未检测到角色，使用默认: %s", default)
            state["role_type"] = default
            state["final_response"] = greeting
            return state

        # --- 已有角色，不改变任何状态 ---
        logger.debug("[select_role] 保持当前角色: %s", state.get("role_type"))
        return state

    def _emotion_node(self, state: AgentState) -> AgentState:
        """节点2：情感分析"""
        user_msg = state.get("user_input", "")
        if not user_msg:
            logger.warning("[emotion] state 缺少 user_input，使用空字符串")
            emotion = {"label": "neutral", "score": 0.5}
        else:
            emotion = self.emotion_svc.analyze(user_msg)

        logger.info("[emotion] 结果: label=%s, score=%.2f", emotion.get("label"), emotion.get("score"))
        state["emotion"] = emotion
        return state

    def _memory_node(self, state: AgentState) -> AgentState:
        """节点3：记忆检索"""
        user_msg = state["user_input"]
        role_type = state.get("role_type", "温柔贤淑型")  # 获取当前角色
        logger.info("[memory] 检索记忆: %s", user_msg[:50])
        mem_text = self.memory_svc.retrieve(
            user_id= state["user_id"],
            query=user_msg,
            role_type=role_type # 传入当前角色
        )
        logger.info("[memory] 检索到 %d 字符的记忆", len(mem_text))
        state["memory_text"] = mem_text
        return state

    def _generate_node(self, state: AgentState) -> AgentState:
        """节点4：整合信息生成最终回复"""
        # 如果已有开场白且不是重新生成，则直接返回（避免覆盖）
        if state.get("final_response") and not state.get("need_regenerate"):
            logger.debug("[generate] 使用开场白，跳过生成")
            return state

        role_type = state.get("role_type", "温柔贤淑型")
        emotion = state.get("emotion", {"label": "neutral", "score": 0.5})
        memory_text = state.get("memory_text", "")
        user_id = state["user_id"]
        user_input = state["user_input"]

        # 获取情绪应对策略
        style = EmotionService.get_emotion_style(emotion["label"], emotion["score"])
        logger.debug("[generate] 角色=%s, 情绪策略=%s", role_type, style[:30])

        # 获取好感度与解锁状态
        aff = self.affection_svc.get(user_id, role_type)
        unl = self.affection_svc.get_unlock_state(user_id, role_type)
        aff_info = f"亲密度{aff['intimacy']:.0f}, 信任{aff['trust']:.0f}"
        unlock_info = ""
        if unl["level"] >= 2:
            unlock_info += "关系亲密，说话更随意。"
        if unl["story_unlocked"]:
            unlock_info += "可分享角色小秘密。"
        if unl["avatar_upgraded"]:
            unlock_info += "角色换了新衣服。"
        logger.debug("[generate] 好感度: %s, 解锁等级: %d", aff_info, unl["level"])

        # 构建系统提示词
        system_prompt = PromptFactory.system_prompt(
            role_type, style, memory_text, aff_info, unlock_info
        )

        # 处理重新生成逻辑
        if state.get("need_regenerate") and state.get("regenerate_context"):
            ctx = state["regenerate_context"]
            human_content = PromptFactory.regenerate(ctx["user_msg"], ctx["ai_msg"])
            logger.info("[generate] 重新生成回复，原文: %s", ctx["user_msg"][:30])
        else:
            human_content = user_input

        # 调用 LLM 生成回复
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_content),
        ]
        resp = self.llm.invoke(messages)
        final_text = resp.content
        logger.info("[generate] 回复: %s...", final_text[:50])

        # 存储记忆和更新好感度（非重新生成时）
        # 调用记忆存储
        if not state.get("need_regenerate"):
            self.memory_svc.store(
                user_id=state["user_id"],
                user_msg=state["user_input"],
                ai_reply=final_text,
                emotion=emotion,
                role_type=role_type  # 传入当前角色
            )
            delta = self.affection_svc.calculate_delta(user_input, final_text, emotion)
            self.affection_svc.update(user_id, role_type, delta)
            logger.debug("[generate] 记忆已存储，好感度已更新")

        state["final_response"] = final_text
        state["need_regenerate"] = False
        return state

    # -------------------- 图构建（使用 AgentState 类型） --------------------
    def _build_graph(self):
        """用 LangGraph 构建节点流水线"""
        workflow = StateGraph(AgentState)   # 显式指定状态类型

        workflow.add_node("select_role", self._select_role_node)
        workflow.add_node("emotion", self._emotion_node)
        workflow.add_node("memory", self._memory_node)
        workflow.add_node("generate", self._generate_node)

        # 定义边：顺序执行
        workflow.set_entry_point("select_role")
        workflow.add_edge("select_role", "emotion")
        workflow.add_edge("emotion", "memory")
        workflow.add_edge("memory", "generate")
        workflow.add_edge("generate", END)

        compiled = workflow.compile(checkpointer=self.checkpointer)
        logger.info("LangGraph 状态图构建完成")
        return compiled

    def invoke(self, state: AgentState, config: RunnableConfig = None) -> AgentState:
        """
         执行一次对话
         Args:
             state: 符合 AgentState 结构的字典
             config: LangGraph 运行配置（包含 thread_id）
         Returns:
             执行后的完整 AgentState（包含 final_response 等字段）
         """
        if config is None:
            config = {"configurable": {"thread_id": state.get("user_id", "default")}}
        logger.info("Agent.invoke 开始, thread_id=%s", config["configurable"]["thread_id"][:8])
        result = self.graph.invoke(state, config)
        logger.info("Agent.invoke 结束, 回复长度=%d", len(result.get("final_response", "")))
        return result