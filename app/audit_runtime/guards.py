from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""


def ensure_analysis_available(has_analysis: bool) -> GuardResult:
    if has_analysis:
        return GuardResult(True, "")
    return GuardResult(False, "请先运行 A-101 数据分析")
