from __future__ import annotations

import hashlib
import re

REDACTION_RULES = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[邮箱已隐藏]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号已隐藏]"),
    (re.compile(r"(?i)https?://\S+|www\.\S+"), "[链接已隐藏]"),
    (re.compile(r"(?i)(?:QQ|企鹅|q号)\s*[:：]?\s*[1-9]\d{4,11}"), "[QQ已隐藏]"),
]


def sanitize_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    for pattern, replacement in REDACTION_RULES:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:5000]


def anonymize_author(author: str | None, salt: str) -> str:
    raw = (author or "anonymous").strip().encode("utf-8", errors="ignore")
    digest = hashlib.sha256(salt.encode("utf-8") + raw).hexdigest()[:4].upper()
    return f"匿名用户 #{digest}"
