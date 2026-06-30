# EchoSoul Skills 目录

本目录包含 EchoSoul 虚拟伴侣的技能定义文件。

## 约定

- 每个 Skill 一个子目录
- 每个子目录必须包含 `SKILL.md` 文件
- SKILL.md 遵循 Anthropic Agent Skills 开放标准

## SKILL.md 格式

```
---
name: skill-name
version: 1.0.0
description: 一句话描述
trigger: 触发关键词1, 触发关键词2
---

## Overview
这个技能是做什么的。

## Capabilities
- 能力1
- 能力2

## Triggers
- 用户说某某话时触发

## Tool Definitions
```json
{"name": "tool_name", "description": "...", "parameters": {...}}
```

## Examples
- 用户: "xxx" → AI调用 xxx工具
```

## 已安装的 Skill

| Skill | 描述 | 触发器 |
|-------|------|--------|
| memory-recall | 记忆检索与存储 | "还记得""之前说过" |
| emotion-awareness | 情绪感知与响应 | "心情""感觉" |
| game-actions | 游戏化养成操作 | "任务""成就""皮肤" |
| story-branching | 互动叙事 | "讲故事""继续故事" |
