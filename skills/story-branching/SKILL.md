---
name: story-branching
version: 1.0.0
description: 互动叙事系统，支持多分支故事共创，AI伴侣作为故事中的角色
trigger: 讲故事, 继续故事, 故事, 剧情, 异世界, 悬疑
---

## Overview

互动叙事技能让 AI 伴侣化身为故事中的角色，与用户共同创作多分支故事。
支持预设故事起点（异世界、悬疑、科幻）和自由推进。

## Capabilities

- **progress_story**: 推进互动叙事（开始/选择/自由输入）
- 预设 3 类故事起点
- AI 实时生成后续剧情和选项
- 存档/读档/归档

## Triggers

- 用户说"给我讲个故事"
- 用户说"继续上次的故事"
- 用户说"我选第3个"

## Tool Definitions

```json
{
  "name": "progress_story",
  "description": "推进互动叙事（开始新故事/做出选择/自由输入）",
  "parameters": {
    "type": "object",
    "properties": {
      "action": {"type": "string", "enum": ["get_starters", "start_story", "make_choice", "free_text"]},
      "title": {"type": "string"},
      "story_id": {"type": "integer"},
      "choice_id": {"type": "integer"},
      "text": {"type": "string"}
    },
    "required": ["action"]
  }
}
```

## Examples

- 用户: "给我讲个故事" → AI调用 progress_story(action="get_starters")
- 用户: "开始异世界后宫那个" → AI调用 progress_story(action="start_story", title="初临异界·命运的邂逅")
