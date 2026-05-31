"""
提示词工厂
所有提示词模板集中管理，便于调优和 A/B 测试
"""
from app.roles import Role, RoleCatalog

class PromptFactory:
    """无状态的提示词构建器"""

    @staticmethod
    def system_prompt(
            role_type: str,
            emotion_style: str,
            memory_text: str,
            aff_info: str = "",
            unlock_info: str = ""
    ) -> str:
        """
        构建注入 LLM 的系统提示词，整合角色人设、情绪策略、记忆片段和好感度状态。

        Args:
            role_type: 角色类型，如 "日系动漫型"
            emotion_style: 当前情绪应对策略文本
            memory_text: 用户长期记忆摘要
            aff_info: 好感度信息（如 "亲密度10, 信任10"）
            unlock_info: 解锁状态信息（如 "关系亲密，说话更随意"）

        Returns:
            完整的系统提示词字符串
        """
        role = RoleCatalog.get_role(role_type)

        parts = [
            f"你叫{role.name}。",
            role.persona,
            "",
            "【说话风格】",
            role.style,
            "",
            "【当前情绪应对策略】",
            emotion_style,
            "",
            "【关于用户的记忆】",
            memory_text if memory_text.strip() else "暂无记忆",
            "",
            "【你们的关系状态】",
            aff_info if aff_info.strip() else "暂无数据",
            unlock_info if unlock_info.strip() else "",
            "",
            "请严格遵循以上设定，用中文进行对话。",
        ]

        return "\n".join(parts)


    @staticmethod
    def emotion_analysis_system() -> str:
        """情感分析的系统指令，要求输出 JSON 结构"""
        return (
            "你是一位极其敏锐的情绪分析专家。请仔细阅读用户文本，捕捉任何可能的情绪色彩，"
            "包括高兴、难过、生气、好奇、失望、期待、无聊等。除非文本绝对中性（如纯事实陈述），"
            "否则你必须选择一个具体的情绪标签，而不是 neutral。"
            "输出格式：JSON 对象，包含 label（从给定标签列表中选择）和 score（0-1的置信度）。"
        )

    @staticmethod
    def emotion_analysis_user(text: str) -> str:
        """情感分析的用户消息，包裹待分析文本"""
        return f"待分析文本：{text}"

    @staticmethod
    def memory_extraction(user_msg: str, ai_reply: str) -> str:
        """记忆提取提示词，指导模型提取用户相关的关键信息"""
        return (
            "请从下方对话中提取关于用户的事实、偏好、情绪、计划或兴趣，"
            "包括从提问中可合理推断的信息。例如，用户询问某部作品，表示对其感兴趣。"
            "用第三人称概括，每条不超过20字，用换行分隔。\n"
            "示例：\n"
            "用户：你看过《学战都市》吗？\nAI：当然！\n关键信息：用户对《学战都市》感兴趣\n"
            "如果确实没有任何信息，才输出“无”。\n"
            f"对话：\n用户：{user_msg}\nAI：{ai_reply}\n关键信息："
        )

    @staticmethod
    def proactive_message(role: Role, avg_affection: float) -> str:
        """根据好感度生成不同风格的主动消息提示"""
        if avg_affection < 15:
            return (f"你是{role.name}，{role.persona}。用户很久没理你了，你有点小情绪，"
                    "请发一句闹脾气但可爱的消息，不超过30字。")
        elif avg_affection >= 70:
            return (f"你是{role.name}，和用户关系很好。ta几个小时没出现，"
                    "发一句想念或关心的消息，不超过30字。")
        else:
            return (f"你是{role.name}，用户一阵子没说话了，"
                    "发一句自然关心或分享一个小话题，不超过30字。")

    @staticmethod
    def regenerate(user_msg: str, ai_msg: str) -> str:
        """用户表示不满意时，要求重新生成回复的提示"""
        return f"用户之前说：{user_msg}\n你的上一条回复：{ai_msg}\n用户表示不满意，请换方式重新回答并道歉。"