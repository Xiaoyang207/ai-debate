"""
辩论记录导出功能。

提供将历史记录导出为 Markdown 或 JSON 格式的工具函数。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List


def generate_debate_summary(history: List[Dict[str, Any]]) -> str:
    """从历史记录生成辩论摘要（发言次数、字数统计）。

    Args:
        history: 辩论消息列表，每项包含 type, role, content, stage_key 等字段。

    Returns:
         Markdown 格式的摘要字符串。
    """
    pro_count = con_count = 0
    pro_total_chars = con_total_chars = 0
    stages: Dict[str, Dict[str, int]] = {}

    for msg in history:
        if msg.get("type") != "message":
            continue
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "ProSpeaker":
            pro_count += 1
            pro_total_chars += len(content)
        elif role == "ConSpeaker":
            con_count += 1
            con_total_chars += len(content)
        stage_key = msg.get("stage_key", "unknown")
        stages.setdefault(stage_key, {"pro": 0, "con": 0})
        if role == "ProSpeaker":
            stages[stage_key]["pro"] += 1
        else:
            stages[stage_key]["con"] += 1

    summary = "## 辩论摘要\n\n"
    summary += f"- 正方发言次数：{pro_count}，总字数：{pro_total_chars}\n"
    summary += f"- 反方发言次数：{con_count}，总字数：{con_total_chars}\n\n"
    if stages:
        summary += "### 各环节统计\n"
        for sk, counts in stages.items():
            summary += f"- {sk}：正方 {counts['pro']} 轮，反方 {counts['con']} 轮\n"
    return summary


def export_to_markdown(history: List[Dict[str, Any]], topic: str) -> str:
    """将辩论历史导出为 Markdown 格式。

    Args:
        history: 辩论消息列表。
        topic: 辩题。

    Returns:
        Markdown 字符串。
    """
    md = f"# 辩论记录：{topic}\n\n"
    md += f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n"
    current_stage = None
    for msg in history:
        if msg["type"] == "stage":
            current_stage = msg.get("stage_name", "未知环节")
            md += f"## {current_stage}\n\n"
        elif msg["type"] == "message":
            role = "正方" if msg["role"] == "ProSpeaker" else "反方"
            speaker = msg.get("speaker_name", role)
            content = msg.get("content", "")
            md += f"**{role} ({speaker})**：\n\n{content}\n\n---\n\n"
        elif msg["type"] == "warning":
            md += f"> ⚠️ {msg['content']}\n\n"
        elif msg["type"] == "error":
            md += f"> ❌ {msg['content']}\n\n"
    md += "\n" + generate_debate_summary(history)
    return md


def export_to_json(history: List[Dict[str, Any]], topic: str) -> str:
    """将辩论历史导出为 JSON 格式。

    Args:
        history: 辩论消息列表。
        topic: 辩题。

    Returns:
        JSON 字符串。
    """
    export_data = {
        "topic": topic,
        "export_time": datetime.now().isoformat(),
        "messages": history,
        "summary": generate_debate_summary(history),
    }
    return json.dumps(export_data, ensure_ascii=False, indent=2)