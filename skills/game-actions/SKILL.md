---
name: game-actions
version: 1.0.0
description: 游戏化养成系统操作，包括每日任务、成就系统、皮肤管理
trigger: 任务, 成就, 皮肤, 每日, 奖励, 养成
---

## Overview

游戏化养成技能让用户通过对话即可完成游戏系统操作。
AI 伴侣可以帮用户查看每日任务、检查成就进度、管理皮肤等。

## Capabilities

- **check_achievements**: 查看成就解锁进度
- **do_game_action**: 执行游戏动作（完成任务/查看皮肤/装备皮肤）
- 每日任务自动分配和完成

## Triggers

- 用户说"今天有什么任务"
- 用户说"看看我的成就"
- 用户说"换个皮肤"
- 用户完成了游戏相关行为

## Tool Definitions

```json
{
  "name": "check_achievements",
  "description": "查询用户的游戏化成就进度",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

```json
{
  "name": "do_game_action",
  "description": "执行游戏养成动作（完成任务/查看皮肤/装备皮肤）",
  "parameters": {
    "type": "object",
    "properties": {
      "action": {"type": "string", "enum": ["complete_task", "get_tasks", "get_skins", "equip_skin"]},
      "task_id": {"type": "integer"},
      "skin_id": {"type": "integer"}
    },
    "required": ["action"]
  }
}
```

## Examples

- 用户: "今天有什么任务" → AI调用 do_game_action(action="get_tasks")
- 用户: "我完成早安问候了" → AI调用 do_game_action(action="complete_task", task_id=1)
