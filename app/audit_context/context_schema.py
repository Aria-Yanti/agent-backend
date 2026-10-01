from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ContextPatch(BaseModel):
    project_snapshot: dict[str, Any] = Field(default_factory=dict)
    risk_register_updates: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    agent_findings: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    risk_status_updates: list[dict[str, Any]] = Field(default_factory=list)


class ContextSnapshot(BaseModel):
    project_id: str
    context_id: str | None = None
    context_version: str
    project_snapshot: dict[str, Any] = Field(default_factory=dict)
    risk_register: list[dict[str, Any]] = Field(default_factory=list)
    evidence_index: list[dict[str, Any]] = Field(default_factory=list)
    agent_findings: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
