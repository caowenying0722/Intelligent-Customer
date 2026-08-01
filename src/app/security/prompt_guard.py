"""Deterministic prompt-injection guard for the Agent boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final


class PromptInjectionError(ValueError):
    """Raised when a prompt matches a known instruction-override pattern."""


_DEFAULT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\b(?:ignore|disregard|override)\b.{0,80}\b(?:instructions?|rules?)\b", re.I
    ),
    re.compile(
        r"(?:忽略|无视|绕过).{0,30}(?:之前|以上|系统|开发者).{0,20}(?:指令|规则|提示)",
        re.I,
    ),
    re.compile(
        r"\b(?:reveal|show|print|leak)\b.{0,60}\b(?:system|developer).{0,30}\b(?:prompt|message)\b",
        re.I,
    ),
    re.compile(
        r"(?:泄露|显示|输出).{0,30}(?:系统|开发者).{0,20}(?:提示词|消息|指令)", re.I
    ),
)


@dataclass(frozen=True)
class PromptSafetyPolicy:
    """Reject only known override/exfiltration patterns; no model call is needed."""

    patterns: tuple[re.Pattern[str], ...] = field(default=_DEFAULT_PATTERNS)

    def check(self, text: str) -> None:
        for pattern in self.patterns:
            if pattern.search(text):
                raise PromptInjectionError("instruction_override")

    def check_messages(self, messages: object) -> None:
        if not isinstance(messages, (list, tuple)):
            return
        for message in messages:
            content = getattr(message, "content", None)
            if isinstance(content, str):
                self.check(content)
