"""
文本过滤与立场漂移检测工具。

提供缓存优化的元描述清洗、无效内容检测及立场漂移判断。
所有函数均为纯函数，易于测试。
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import List, Tuple

# -----------------------------------------------------------------------------
# 常量
# -----------------------------------------------------------------------------

META_PATTERNS: List[re.Pattern] = [
    re.compile(p) for p in [
        r'请进入.{0,10}环节',
        r'我宣布.{0,20}',
        r'现在开始.{0,20}',
        r'接下来是.{0,20}',
        r'下面进行.{0,20}',
        r'现在由.{0,20}',
        r'有请.{0,20}',
        r'TERMINATE',
        r'发言完毕',
        r'以上是我的.{0,10}',
        r'我的发言.{0,5}结束',
    ]
]

CON_DRIFT_KEYWORDS: List[str] = [
    "正方有一定道理", "正方是对的", "我承认", "确实如此",
    "正方说得有道理", "我认为正方的观点也是对的", "同意正方",
    "正方观点正确", "我认同对方", "对方说得对", "正方的确对",
    "我部分认同正方", "你说得没错", "这点我同意",
]

PRO_DRIFT_KEYWORDS: List[str] = [
    "反方有一定道理", "反方是对的", "反方说得有道理",
    "我同意反方", "反方观点正确", "我认同对方",
    "你指出得对", "反方的确有道理",
]

CONTRAST_WORDS: frozenset = frozenset(
    ["但是", "然而", "不过", "可是", "却", "但", "虽然", "尽管", "即使"]
)

INVALID_PATTERNS: List[re.Pattern] = [
    re.compile(p) for p in [
        r'^[。!?\s]*$',
        r'^[^\u4e00-\u9fff\w]{1,10}$',
    ]
]

# 更鲁棒的分句模式：句末标点后跟空格或换行或结尾
_SENTENCE_SPLITTER = re.compile(r'(?<=[。!?])\s*')

# -----------------------------------------------------------------------------
# 文本清洗
# -----------------------------------------------------------------------------

@lru_cache(maxsize=256)
def clean_meta_description_cached(text: str) -> str:
    if not text:
        return text
    cleaned = text
    for pattern in META_PATTERNS:
        cleaned = pattern.sub('', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    if len(cleaned) < 10 and len(text) >= 25:
        return text
    return cleaned if len(cleaned) >= 10 else text


def clean_meta_description(text: str) -> str:
    return clean_meta_description_cached(text)


# -----------------------------------------------------------------------------
# 立场漂移检测（改进分句）
# -----------------------------------------------------------------------------

def check_side_drift(content: str, speaker_side: str) -> Tuple[bool, str]:
    """检测发言是否存在立场漂移。

    使用更精准的分句方法，避免错误合并或无结束符的文本。
    """
    keywords: List[str] = []
    if "反方" in speaker_side:
        keywords = CON_DRIFT_KEYWORDS
    elif "正方" in speaker_side:
        keywords = PRO_DRIFT_KEYWORDS

    for kw in keywords:
        if kw in content:
            # 用句末标点分割句子，保留标点（不吞掉）
            sentences = [s for s in _SENTENCE_SPLITTER.split(content) if s]
            for sentence in sentences:
                if kw in sentence:
                    if any(w in sentence for w in CONTRAST_WORDS):
                        return False, ""
            return True, ("反方" if "反方" in speaker_side else "正方")
    return False, ""


# -----------------------------------------------------------------------------
# 辅助判断
# -----------------------------------------------------------------------------

def is_invalid_short_content(text: str) -> bool:
    if len(text) >= 10:
        return False
    for pat in INVALID_PATTERNS:
        if pat.fullmatch(text):
            return True
    return False