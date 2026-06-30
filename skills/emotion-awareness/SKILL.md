---
name: emotion-awareness
version: 1.0.0
description: 感知用户情绪状态并调整回复风格，让AI伴侣的回应更有温度
trigger: 心情, 感觉, 情绪, 难过, 开心, 焦虑, 无聊
---

## Overview

情绪感知技能让 AI 伴侣通过情绪分析了解用户当前的心理状态，
并根据情绪调整回复风格。当用户表现出明显的情绪变化时自动触发。

## Capabilities

- **read_emotion**: 分析当前对话中的用户情绪
- 自动调整回复风格（开心时活泼，难过时温柔）
- 情绪追踪，识别长期情绪模式

## Triggers

- 用户说"我今天心情..."
- 用户表达强烈情绪（难过/开心/焦虑等）
- 用户说"我有点..."

## Tool Definitions

```json
{
  "name": "read_emotion",
  "description": "获取当前对话的情绪分析结果，包括用户情绪标签和强度",
  "parameters": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

## Examples

- 用户: "我今天心情特别好" → AI调用 read_emotion()，回复时采用活泼风格
- 用户: "最近压力好大" → AI调用 read_emotion()，回复时给予支持
