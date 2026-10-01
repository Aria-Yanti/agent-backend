from __future__ import annotations

import json
import re
from typing import Any

JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.DOTALL)
NAKED_OBJECT_RE = re.compile(r"(\{[\s\S]*\})", re.DOTALL)

DSML_ANY_TAG_RE = re.compile(r"</?[｜|][\s\S]{0,40}?DSML[\s\S]{0,80}?>", re.IGNORECASE)
NAKED_TOOLCALL_RE = re.compile(r"</?tool_calls?>", re.IGNORECASE)
INVOKE_BLOCK_RE = re.compile(r"</?invoke[^>]*>", re.IGNORECASE)
PARAMETER_BLOCK_RE = re.compile(r"</?parameter[^>]*>", re.IGNORECASE)
LINE_NOISE_PATTERNS = (
    re.compile(r"^\s*(?:Let me|Now I (?:have|will)|I will|I'll|I'm going to)\b.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*function call.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*tool result.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*json parse failed.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*raw[_ ]output[:：].*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*fs_(?:list|read|write|append)_?\w*\s*\(.*$", re.IGNORECASE | re.MULTILINE),
)
FILESYSTEM_REFUSAL_HINTS = (
    "filesystem capability",
    "i cannot access files",
    "无法读取本地文件",
    "未启用文件",
    "未授予文件",
)


def strip_tool_noise(text: str) -> str:
    """Remove DSML tool-call XML, naked <tool_calls>, leading "Let me…" lines, etc.

    These leak in when the LLM emits the tool-use protocol as plain text instead
    of through the structured channel. We surgically delete those fragments so
    the audit Audit.md does not get polluted with technical noise.
    """
    if not text:
        return ""
    cleaned = str(text)
    for _ in range(3):
        new_cleaned = DSML_ANY_TAG_RE.sub("", cleaned)
        if new_cleaned == cleaned:
            break
        cleaned = new_cleaned
    cleaned = NAKED_TOOLCALL_RE.sub("", cleaned)
    cleaned = INVOKE_BLOCK_RE.sub("", cleaned)
    cleaned = PARAMETER_BLOCK_RE.sub("", cleaned)
    for pattern in LINE_NOISE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

PATCH_KEYS = (
    "agent_findings",
    "risk_register_updates",
    "evidence_refs",
    "evidence_index_updates",
    "next_actions",
    "misstatement_summary",
    "review_required_items",
    "review_gates",
    "review_decisions",
    "open_questions",
    "skill_calls",
)


def _try_load(candidate: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(candidate)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def parse_agent_output(raw: str) -> tuple[str, dict[str, Any]]:
    text = str(raw or "").strip()
    if not text:
        return "", {}

    patch: dict[str, Any] = {}
    for match in JSON_FENCE_RE.finditer(text):
        obj = _try_load(match.group(1))
        if obj is not None:
            patch = obj
            break

    if not patch:
        m = NAKED_OBJECT_RE.search(text)
        if m is not None:
            obj = _try_load(m.group(1))
            if obj is not None:
                patch = obj

    summary_source = JSON_FENCE_RE.sub("", text).strip()
    summary_source = strip_tool_noise(summary_source)
    summary = ""
    if patch:
        raw_summary = patch.get("summary")
        if isinstance(raw_summary, str) and raw_summary.strip():
            summary = strip_tool_noise(raw_summary)
    if not summary:
        summary = summary_source
    if summary:
        summary = " ".join(summary.split())[:400]

    filtered_patch: dict[str, Any] = {}
    for key in PATCH_KEYS:
        if key in patch and patch[key]:
            filtered_patch[key] = patch[key]
    if summary:
        filtered_patch["summary"] = summary

    return summary, filtered_patch


def is_filesystem_refusal(summary: str) -> bool:
    lowered = str(summary or "").lower()
    return any(hint in lowered for hint in FILESYSTEM_REFUSAL_HINTS)


def merge_patches(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (overlay or {}).items():
        if value in (None, "", [], {}):
            continue
        merged[key] = value
    return merged
