from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


AuditEventType = Literal[
    "context_initialized",
    "agent_context_loaded",
    "agent_patch_applied",
    "human_review_required",
    "human_review_decision",
    "skill_call_recorded",
]

ActorType = Literal["master", "agent", "human", "skill"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditContextMetadata(BaseModel):
    last_updated_by: str = ""
    last_updated_at: str = Field(default_factory=utc_now_iso)
    audit_md_path: str = ""


class AuditContextPatch(BaseModel):
    risk_register_updates: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    evidence_index_updates: list[dict[str, Any]] = Field(default_factory=list)
    agent_findings: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    review_required_items: list[dict[str, Any]] = Field(default_factory=list)
    review_gates: list[dict[str, Any]] = Field(default_factory=list)
    review_decisions: list[dict[str, Any]] = Field(default_factory=list)
    misstatement_summary: dict[str, Any] = Field(default_factory=dict)
    open_questions: list[dict[str, Any]] = Field(default_factory=list)
    skill_calls: list[dict[str, Any]] = Field(default_factory=list)


class AuditContextState(BaseModel):
    context_id: str
    project_id: str
    version: int = 0
    project_snapshot: dict[str, Any] = Field(default_factory=dict)
    risk_register: list[dict[str, Any]] = Field(default_factory=list)
    evidence_index: list[dict[str, Any]] = Field(default_factory=list)
    agent_findings: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    review_required_items: list[dict[str, Any]] = Field(default_factory=list)
    review_gates: list[dict[str, Any]] = Field(default_factory=list)
    review_decisions: list[dict[str, Any]] = Field(default_factory=list)
    misstatement_summary: dict[str, Any] = Field(default_factory=dict)
    open_questions: list[dict[str, Any]] = Field(default_factory=list)
    skill_calls: list[dict[str, Any]] = Field(default_factory=list)
    validation_results: list[dict[str, Any]] = Field(default_factory=list)
    trust_score: float = 0.0
    paused: bool = False
    pause_step: str = ""
    pause_reason: str = ""
    metadata: AuditContextMetadata = Field(default_factory=AuditContextMetadata)


class AuditContextEvent(BaseModel):
    event_id: str
    context_id: str
    project_id: str
    version_before: int
    version_after: int
    event_type: AuditEventType
    actor_type: ActorType
    actor_name: str
    task_role: str = ""
    task_title: str = ""
    patch_keys: list[str] = Field(default_factory=list)
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
