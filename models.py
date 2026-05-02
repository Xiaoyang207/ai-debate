"""
领域模型与配置。

该模块定义了辩论应用的核心数据结构，包括不可变配置、环节定义、
用户级应用配置等。所有数据类使用 `dataclass` 并尽可能不可变。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List

# -----------------------------------------------------------------------------
# 日志（模块级，不配置 handler，由调用方决定）
# -----------------------------------------------------------------------------
logger = logging.getLogger("debate_app.models")

# -----------------------------------------------------------------------------
# 常量
# -----------------------------------------------------------------------------
CONFIG_FILE: str = "debate_config.json"  # 用户持久化配置文件路径

# 辩论四环节的名称与职责定义，可扩展
STAGE_DEFS: List[Dict[str, str]] = [
    {
        "key": "stage1",
        "name": "第一环节：立论陈词（一辩）",
        "icon": "📌",
        "pro_duty": "提出正方核心观点（3个论点+论据），宣布辩题并开场立论",
        "con_duty": "提出反方核心观点（3个论点+论据），逐条反驳正方立论",
        "pro_speaker": "正方一辩",
        "con_speaker": "反方一辩",
    },
    {
        "key": "stage2",
        "name": "第二环节：攻辩交锋（二辩）",
        "icon": "⚔️",
        "pro_duty": "反驳反方一辩，指出逻辑漏洞，补充正方新论据，揭露对方论据缺陷",
        "con_duty": "维护反方立场，回击正方二辩论点，揭示正方论据漏洞",
        "pro_speaker": "正方二辩",
        "con_speaker": "反方二辩",
    },
    {
        "key": "stage3",
        "name": "第三环节：质询追问（三辩）",
        "icon": "🎯",
        "pro_duty": "深入追问反方核心论据，质询证据链，揭示反方论点深层问题",
        "con_duty": "深入维护反方论据，质询正方证据链，揭示正方逻辑深层问题",
        "pro_speaker": "正方三辩",
        "con_speaker": "反方三辩",
    },
    {
        "key": "stage4",
        "name": "第四环节：总结陈词（四辩）",
        "icon": "🏁",
        "pro_duty": "全面回顾全场辩论，升华正方立场，做最有力最终总结",
        "con_duty": "全面回顾全场辩论，强化反方立场，指出正方致命漏洞做最终总结",
        "pro_speaker": "正方四辩",
        "con_speaker": "反方四辩",
    },
]

# 预设辩题
PRESET_TOPICS: List[str] = [
    "人工智能的发展利大于弊还是弊大于利",
    "网络是否使人际关系更疏远",
    "应不应该废除死刑",
    "全球化对发展中国家有利还是有害",
]

# 主题色板
THEMES: Dict[str, Dict[str, str]] = {
    "暗色": {
        "bg_main": "#0f172a", "bg_panel": "#1e293b", "bg_card": "#0f172a",
        "bg_entry": "#0f172a", "fg_title": "#e2e8f0", "fg_label": "#e2e8f0",
        "fg_sec": "#64748b", "fg_entry": "#e2e8f0", "btn_bg": "#f59e0b",
        "btn_fg": "#1a1a1e", "btn_disabled_bg": "#475569",
        "btn_secondary_bg": "#334155", "btn_secondary_fg": "#94a3b8",
        "progress_bg": "#334155", "progress_trough": "#0f172a",
        "highlight": "#1e293b", "separator": "#334155",
    },
    "亮色": {
        "bg_main": "#f0f4f8", "bg_panel": "#ffffff", "bg_card": "#f8fafc",
        "bg_entry": "#ffffff", "fg_title": "#0f172a", "fg_label": "#1e293b",
        "fg_sec": "#475569", "fg_entry": "#0f172a", "btn_bg": "#0ea5e9",
        "btn_fg": "#ffffff", "btn_disabled_bg": "#cbd5e1",
        "btn_secondary_bg": "#e2e8f0", "btn_secondary_fg": "#334155",
        "progress_bg": "#e2e8f0", "progress_trough": "#f1f5f9",
        "highlight": "#e0f2fe", "separator": "#e2e8f0",
    },
}

# 所有合法的阶段键集合（用于验证）
VALID_STAGE_KEYS = {d["key"] for d in STAGE_DEFS}

# -----------------------------------------------------------------------------
# 配置类
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class DebateConfig:
    """不可变的辩论全局配置，由 UI 收集后传递给引擎。

    所有字段必须通过构造函数提供，对象创建后不可修改。
    """

    topic: str                              # 辩题
    stages: Dict[str, int]                  # 每环节轮数，如 {'stage1': 1, ...}
    word_limit: int                         # 单次发言字数上限
    pro_first: bool                         # 正方是否先发言
    api_key: str                            # API 密钥（不落盘）
    base_url: str = "https://api.deepseek.com/"
    model: str = "deepseek-v4-pro"
    max_tokens: int = 0                     # 单条消息 token 截断上限（0=不限）
    temperature: float = 0.7
    sleep_between_messages: float = 0.3     # 消息间隔秒数

    def __post_init__(self) -> None:
        """验证配置合法性。"""
        if not self.topic.strip():
            raise ValueError("辩题不能为空")
        # 检查 stages 的键是否都合法
        if not set(self.stages.keys()).issubset(VALID_STAGE_KEYS):
            raise ValueError(f"环节配置包含无效 key，允许的 key 为: {VALID_STAGE_KEYS}")
        # 检查轮数是否非负
        for k, v in self.stages.items():
            if not isinstance(v, int) or v < 0:
                raise ValueError(f"环节 {k} 的轮数必须为非负整数")
        if self.word_limit < 10:
            raise ValueError("字数限制不能小于10")


class AppConfig:
    """用户应用级配置（窗口大小、字体、主题），提供持久化读写。"""

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {
            "geometry": "1050x850",
            "font_size": 11,
            "theme": "暗色",
        }

    def load(self) -> None:
        """从磁盘加载配置，不存在的键保持默认值。"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._data.update(data)
            except Exception:
                logger.exception("加载应用配置失败，使用默认值")

    def save(self) -> None:
        """保存当前配置到磁盘。"""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("保存应用配置失败")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value