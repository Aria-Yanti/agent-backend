from __future__ import annotations

from typing import Any


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_dict_list(items: Any, default_keys: tuple[str, ...] = ("description",)) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            normalized.append(dict(item))
            continue
        text = _as_str(item)
        if not text:
            continue
        normalized.append({default_keys[0]: text})
    return normalized


def _dedupe_dict_list(items: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = ""
        for field in key_fields:
            value = item.get(field)
            if value:
                key = _as_str(value)
                break
        if not key:
            key = str(sorted(item.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def normalize_patch_payload(patch: dict[str, Any] | None, agent_name: str, task_role: str, summary: str) -> dict[str, Any]:
    payload = dict(patch or {})

    raw_actions = payload.get("next_actions") or []
    actions: list[dict[str, Any]] = []
    for item in raw_actions:
        if isinstance(item, dict):
            description = _as_str(item.get("description"))
            if not description:
                continue
            actions.append({"description": description, "priority": _as_str(item.get("priority")) or "medium"})
        else:
            description = _as_str(item)
            if description:
                actions.append({"description": description, "priority": "medium"})
    payload["next_actions"] = actions

    raw_evidence = payload.get("evidence_refs") or []
    deduped_evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_evidence:
        if isinstance(item, dict):
            key = _as_str(item.get("evidence_code") or item.get("file_name") or item.get("name"))
            if not key:
                key = str(sorted(item.items()))
            normalized_item = dict(item)
        else:
            key = _as_str(item)
            if not key:
                continue
            normalized_item = {"evidence_code": key, "source": "agent_patch"}
        if not key or key in seen:
            continue
        seen.add(key)
        deduped_evidence.append(normalized_item)
    payload["evidence_refs"] = deduped_evidence

    raw_index_updates = payload.get("evidence_index_updates") or []
    coerced_index_updates: list[dict[str, Any]] = []
    for item in raw_index_updates:
        if isinstance(item, dict):
            coerced_index_updates.append(dict(item))
        else:
            text = _as_str(item)
            if text:
                coerced_index_updates.append({"evidence_code": text, "source": "agent_patch"})
    payload["evidence_index_updates"] = coerced_index_updates

    raw_findings = payload.get("agent_findings") or []
    findings: list[dict[str, Any]] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            text = _as_str(item)
            if not text:
                continue
            findings.append({
                "agent_name": agent_name,
                "task_role": task_role,
                "summary": text,
                "risk_id": "A-101",
            })
            continue
        merged = dict(item)
        merged.setdefault("agent_name", agent_name)
        merged.setdefault("task_role", task_role)
        if not _as_str(merged.get("summary")):
            merged["summary"] = summary or "该 Agent 已完成任务，但未返回结构化 patch。"
        merged.setdefault("risk_id", "A-101")
        findings.append(merged)
    if not findings:
        findings = [{
            "agent_name": agent_name,
            "task_role": task_role,
            "summary": summary or "该 Agent 已完成任务，但未返回结构化 patch。",
            "risk_id": "A-101",
        }]
    payload["agent_findings"] = findings

    payload["risk_register_updates"] = _dedupe_dict_list(
        _normalize_dict_list(payload.get("risk_register_updates"), default_keys=("title",)),
        key_fields=("risk_id", "risk_code", "title"),
    )

    payload["review_required_items"] = _normalize_dict_list(payload.get("review_required_items"))
    payload["review_decisions"] = _normalize_dict_list(payload.get("review_decisions"))
    payload["review_gates"] = _normalize_dict_list(payload.get("review_gates"))
    payload["open_questions"] = _normalize_dict_list(payload.get("open_questions"))
    payload["skill_calls"] = _normalize_dict_list(payload.get("skill_calls"))

    if not isinstance(payload.get("misstatement_summary"), dict):
        payload["misstatement_summary"] = {}

    return payload
