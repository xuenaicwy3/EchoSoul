---
name: memory-recall
version: 1.0.0
description: 检索和存储用户长期记忆，让AI伴侣记住用户说过的话和偏好
trigger: 还记得, 之前说过, 你记得, 我告诉过你, remember
---

## Overview

记忆检索技能让 AI 伴侣能够在对话中主动查询用户的长期记忆。
当用户提及过去的对话内容或询问"你还记得..."时，此技能自动触发，
将相关的用户偏好、事实和事件检索出来，让回复更个性化。

## Capabilities

- **recall_memory**: 语义搜索用户的历史记忆
- **save_memory**: 从当前对话中提取并存储重要信息
- 自动关联相关记忆片段
- 区分偏好/事实/事件/情感四类记忆

## Triggers

- 用户说"你还记得..."
- 用户说"我之前说过..."
- 用户提"上次聊到..."
- 用户分享新的个人信息

## Tool Definitions

```json
{
  "name": "recall_memory",
  "description": "检索关于用户的长期记忆，包括偏好、事实和过往经历",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "记忆检索关键词"},
      "max_results": {"type": "integer", "description": "最大返回条数", "default": 3}
    },
    "required": ["query"]
  }
}
```

```json
{
  "name": "save_memory",
  "description": "存储用户分享的个人信息到长期记忆",
  "parameters": {
    "type": "object",
    "properties": {
      "fact": {"type": "string", "description": "要存储的事实陈述"},
      "category": {"type": "string", "enum": ["preference", "fact", "event", "emotion"], "default": "fact"}
    },
    "required": ["fact"]
  }
}
```

## Examples

- 用户: "你还记得我喜欢什么颜色吗" → AI调用 recall_memory(query="喜欢的颜色")
- 用户: "我下周一要面试" → AI调用 save_memory(fact="用户下周一有面试", category="event")
