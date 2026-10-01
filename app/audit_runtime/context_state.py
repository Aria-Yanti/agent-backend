from __future__ import annotations

import json
from pathlib import Path

from .schemas import AuditContextEvent, AuditContextState

RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "data" / "audit_runtime"
RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)


def _safe_segment(project_id: str) -> str:
    raw = str(project_id or "default").strip() or "default"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)


def context_path(project_id: str) -> Path:
    return RUNTIME_ROOT / f"{_safe_segment(project_id)}.context.json"


def events_path(project_id: str) -> Path:
    return RUNTIME_ROOT / f"{_safe_segment(project_id)}.events.jsonl"


def _coerce_list_of_dicts(items: object, *, default_key: str = "description") -> list[dict]:
    """Coerce a list-of-anything into list-of-dicts.

    Defensive shim for runtime context files written by earlier code paths or
    by LLM patches that contained bare strings where the schema expects dicts.
    Without this, model_validate_json would refuse to load the file.
    """
    if not isinstance(items, list):
        return []
    coerced: list[dict] = []
    for item in items:
        if isinstance(item, dict):
            coerced.append(item)
        else:
            text = str(item or "").strip()
            if text:
                coerced.append({default_key: text})
    return coerced


def load_context(project_id: str) -> AuditContextState | None:
    path = context_path(project_id)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        list_fields = {
            "risk_register": "title",
            "evidence_index": "evidence_code",
            "agent_findings": "summary",
            "next_actions": "description",
            "review_required_items": "description",
            "review_gates": "description",
            "review_decisions": "description",
            "open_questions": "description",
            "skill_calls": "description",
        }
        for field, default_key in list_fields.items():
            if field in raw:
                raw[field] = _coerce_list_of_dicts(raw[field], default_key=default_key)
    return AuditContextState.model_validate(raw)


def save_context(state: AuditContextState) -> None:
    context_path(state.project_id).write_text(state.model_dump_json(indent=2), encoding="utf-8")


def append_event(event: AuditContextEvent) -> None:
    path = events_path(event.project_id)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.model_dump(), ensure_ascii=False) + "\n")


def list_events(project_id: str) -> list[AuditContextEvent]:
    path = events_path(project_id)
    if not path.exists():
        return []
    items: list[AuditContextEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        items.append(AuditContextEvent.model_validate(json.loads(text)))
    return items
