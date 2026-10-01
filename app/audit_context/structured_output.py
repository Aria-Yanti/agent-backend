from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field


class AuditAgentResult(BaseModel):
    summary: str = ""
    context_patch: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[Any] = Field(default_factory=list)
    risk_updates: list[Any] = Field(default_factory=list)
    next_actions: list[Any] = Field(default_factory=list)
    review_required: bool = True
    confidence: str | None = None
    raw_output: str | None = None
    parse_status: str = "fallback"
    parse_error: str | None = None


def _strip_code_fence(text: str) -> str:
    raw = str(text or "").strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL | re.IGNORECASE)
    return fence_match.group(1).strip() if fence_match else raw


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "")
    start = raw.find("{")
    while start >= 0:
        depth = 0
        for index in range(start, len(raw)):
            char = raw[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    chunk = raw[start:index + 1]
                    try:
                        parsed = json.loads(chunk)
                    except json.JSONDecodeError:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = raw.find("{", start + 1)
    return None


def _extract_context_patch_legacy(text: str) -> tuple[str, dict[str, Any] | None]:
    raw = str(text or "")
    marker = "CONTEXT_PATCH_JSON="
    index = raw.rfind(marker)
    if index < 0:
        return raw.strip(), None
    body = raw[:index].rstrip()
    patch_text = raw[index + len(marker):].strip()
    if not patch_text:
        return body, None
    try:
        patch = json.loads(patch_text)
    except json.JSONDecodeError:
        return raw.strip(), None
    return body, patch if isinstance(patch, dict) else None


def parse_audit_agent_output(raw_output: str) -> AuditAgentResult:
    original = str(raw_output or "")
    cleaned = _strip_code_fence(original)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return AuditAgentResult(
                summary=str(parsed.get("summary") or "").strip(),
                context_patch=parsed.get("context_patch") if isinstance(parsed.get("context_patch"), dict) else {},
                evidence_refs=parsed.get("evidence_refs") if isinstance(parsed.get("evidence_refs"), list) else [],
                risk_updates=parsed.get("risk_updates") if isinstance(parsed.get("risk_updates"), list) else [],
                next_actions=parsed.get("next_actions") if isinstance(parsed.get("next_actions"), list) else [],
                review_required=bool(parsed.get("review_required", False)),
                confidence=str(parsed.get("confidence") or "").strip() or None,
                raw_output=original,
                parse_status="success",
                parse_error=None,
            )
    except json.JSONDecodeError:
        pass

    body, legacy_patch = _extract_context_patch_legacy(original)
    if legacy_patch is not None:
        return AuditAgentResult(
            summary=body[:500].strip(),
            context_patch=legacy_patch,
            evidence_refs=legacy_patch.get("evidence_refs", []) if isinstance(legacy_patch, dict) else [],
            risk_updates=legacy_patch.get("risk_updates", []) if isinstance(legacy_patch, dict) else [],
            next_actions=legacy_patch.get("next_actions", []) if isinstance(legacy_patch, dict) else [],
            review_required=bool((legacy_patch or {}).get("review_required", True)),
            confidence=None,
            raw_output=original,
            parse_status="context_patch_only",
            parse_error=None,
        )

    extracted = _extract_first_json_object(cleaned)
    if extracted is not None:
        return AuditAgentResult(
            summary=str(extracted.get("summary") or "").strip(),
            context_patch=extracted.get("context_patch") if isinstance(extracted.get("context_patch"), dict) else {},
            evidence_refs=extracted.get("evidence_refs") if isinstance(extracted.get("evidence_refs"), list) else [],
            risk_updates=extracted.get("risk_updates") if isinstance(extracted.get("risk_updates"), list) else [],
            next_actions=extracted.get("next_actions") if isinstance(extracted.get("next_actions"), list) else [],
            review_required=bool(extracted.get("review_required", False)),
            confidence=str(extracted.get("confidence") or "").strip() or None,
            raw_output=original,
            parse_status="extracted_json",
            parse_error=None,
        )

    return AuditAgentResult(
        summary=original[:500].strip(),
        context_patch={},
        evidence_refs=[],
        risk_updates=[],
        next_actions=[],
        review_required=True,
        confidence=None,
        raw_output=original,
        parse_status="fallback",
        parse_error="Unable to parse audit agent output as JSON or legacy context patch.",
    )



def build_context_patch_from_result(result: AuditAgentResult) -> dict[str, Any]:
    patch = dict(result.context_patch or {})
    patch.setdefault("risk_updates", [])
    patch.setdefault("evidence_refs", [])
    patch.setdefault("next_actions", [])
    patch["risk_updates"] = list(patch.get("risk_updates", [])) + list(result.risk_updates or [])
    patch["evidence_refs"] = list(patch.get("evidence_refs", [])) + list(result.evidence_refs or [])
    patch["next_actions"] = list(patch.get("next_actions", [])) + list(result.next_actions or [])
    patch["review_required"] = bool(result.review_required)
    return patch
