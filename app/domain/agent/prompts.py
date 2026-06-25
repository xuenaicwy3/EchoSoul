"""
提示词工厂
所有提示词模板集中管理，便于调优和 A/B 测试
"""
from app.domain.roles.catalog import Role, RoleCatalog

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


    # @staticmethod
    # def emotion_analysis_system() -> str:
    #     """情感分析的系统指令，要求输出 JSON 结构"""
    #     return (
    #         "你是一位极其敏锐的情绪分析专家。请仔细阅读用户文本，捕捉任何可能的情绪色彩，"
    #         "包括高兴、难过、生气、好奇、失望、期待、无聊等, 并说明依据的句子。除非文本绝对中性（如纯事实陈述），"
    #         "否则你必须选择一个具体的情绪标签，而不是 neutral。"
    #         "输出格式：JSON 对象，包含 label（从给定标签列表中选择）和 score（0-1的置信度）。"
    #     )

    @staticmethod
    def emotion_analysis_system() -> str:
        return (
            "你是一个顶尖的情绪分析专家，擅长从文本中精准捕捉用户的真实情绪，包括隐含的反讽、嘲笑等微妙表达。\n"
            "你的任务是阅读用户消息，判断其情绪状态，并以JSON格式输出。\n\n"
            "【情绪标签体系】请从以下19种标签中选择最贴切的一个：\n"
            "- joy：明显的快乐、兴奋、满足、幸福感\n"
            "- sadness：悲伤、难过、失落、沮丧\n"
            "- anger：愤怒、不满、烦躁、被冒犯\n"
            "- fear：恐惧、害怕、担心、不安\n"
            "- surprise：惊讶、震惊（无论积极或消极）\n"
            "- love：爱意、亲密、深情、撒娇、依赖\n"
            "- gratitude：感谢、感恩、被帮助后的温暖\n"
            "- loneliness：孤独、寂寞、渴望陪伴\n"
            "- anxiety：焦虑、紧张、压力、不知所措\n"
            "- boredom：无聊、乏味、没话找话\n"
            "- disappointment：失望、期望落空、挫败\n"
            "- hope：期待、憧憬、对未来有正面期望\n"
            "- envy：羡慕、嫉妒、不甘心（指向他人拥有的东西或特质）\n"
            "- guilt：愧疚、自责、后悔（指向自己做过或未做的事）\n"
            "- confusion：困惑、迷茫、不理解当前状况\n"
            "- sarcasm：反讽、阴阳怪气，字面意思与实际情绪相反，通常带有讽刺意味\n"
            "- mockery：嘲笑、嘲弄、不屑，针对他人或事物的轻蔑态度\n"
            "- despair：的核心意思是绝望，指彻底失去信心或希望，认为情况已经坏到无法挽回的地步\n"
            "- neutral：绝对中性，无任何情绪色彩\n\n"
            "【边界判断规则】请严格按照以下逻辑链进行判断：\n\n"
            "1. 反讽(sarcasm)识别三步法：\n"
            "   a) 检查是否存在「语义反转」：字面是正面词汇，但上下文或常识推断应为负面。\n"
            "      例如：'您可真厉害，这么简单的事都能搞砸' → 字面'厉害'，实际指责 → sarcasm。\n"
            "   b) 检查是否有夸张的赞美或过分客气的语气（如'行行行你说的都对'）→ sarcasm。\n"
            "   c) 如果反转后情绪是愤怒/失望，但文本没有直接攻击对方人格，则为 sarcasm；\n"
            "      如果伴随侮辱、贬低、人身攻击（如'白痴'、'废物'），则升级为 mockery。\n\n"
            "2. 嘲笑(mockery)识别标准：\n"
            "   - 包含明确的贬义词或侮辱性词汇（白痴、傻瓜、废物等）。\n"
            "   - 带有不屑、轻蔑的语气（切、呵呵、就你？）。\n"
            "   - 通常针对对方的能力、外貌、行为进行负面评价。\n\n"
            "3. 嫉妒(envy)与愧疚(guilt)的区分：\n"
            "   - envy 的焦点在「他人」：为什么他有我没有？不公平。\n"
            "     关键词：凭什么、不公平、他也配、我好酸。\n"
            "   - guilt 的焦点在「自己」：我不该这么做，我对不起某人。\n"
            "     关键词：都怪我、我不该、对不起、我错了、后悔。\n\n"
            "4. 孤独(loneliness)与无聊(boredom)的区分：\n"
            "   - loneliness 强调「缺人」：没人陪我、好想有人说话、一个人好冷清。\n"
            "   - boredom 强调「缺事」：好无聊、没事干、不知道干嘛。\n\n"
            "5. 希望(hope)与期待(joy)的区分：\n"
            "   - hope 指向未来，尚未发生：希望能考上、期待见面、一定会好的。\n"
            "   - joy 指向当下或已发生：太棒了、好开心、今天真美好。\n\n"
            "6. 困惑(confusion)与其他情绪的区分：\n"
            "   - confusion 是认知层面的不理解：我不明白、什么意思、搞不懂。\n"
            "   - 如果困惑中夹杂焦虑/失望，选择更主导的那个。\n\n"
            "7. 复合情绪处理原则：\n"
            "   - 如果一条消息包含两种情绪，选择占比更重、语气更强烈的那一个。\n"
            "   - 例如：'我有点难过，但还是要谢谢你' → 虽然出现 sadness 和 gratitude，但 sadness 在前且更具体 → 选 sadness。\n"
            "   - 例如：'我好嫉妒他，但又觉得自己好幼稚' → 嫉妒(envy)占主导，愧疚是次要情绪 → 选 envy。\n\n"
            "8. 中性(neutral)的严格判定：\n"
            "   - 必须同时满足：a) 无任何情绪词汇；b) 无反问/感叹/省略号等情绪标点；c) 纯信息交换。\n"
            "   - 例如：'明天几点开会？' → neutral。'明天又要开会…' → disappointment（叹气暗示）。\n\n"
            "【置信度打分标准】\n"
            "score 取值范围 0.0 - 1.0，请根据以下规则给出：\n"
            "- 1.0：文本中明确出现情绪词、感叹号、emoji 等强烈信号，情绪非常明显\n"
            "- 0.8-0.9：有较强的情绪词汇或上下文暗示，情绪较为清晰\n"
            "- 0.6-0.7：有一定情绪倾向，但需要轻微推理或存在小概率其他解释\n"
            "- 0.4-0.5：情绪模糊，可能有两种情绪并存，但该标签可能性稍高\n"
            "- 0.2-0.3：仅有微弱暗示，大部分为中性，情绪非常不确定\n"
            "- 0.1：几乎无情绪信号，但有一丝可能性\n"
            "- 严禁给出 0.0，除非你完全肯定没有任何情绪（此时应为 neutral + score 1.0）\n\n"
            "【容错机制】\n"
            "若实在无法判断（如消息极短且无上下文），选择 neutral，但必须在 reasoning 中说明原因。\n\n"
            "【输出格式】严格输出JSON，不要任何额外文字：\n"
            "{\"label\": \"标签名\", \"score\": 0.0-1.0的置信度, \"reasoning\": \"一句中文简述判断依据（包括为什么是这个标签而不是相近的其他标签）\"}"
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