from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .context_schema import ContextSnapshot
from ..schemas import SharedAuditContextUpdate
from ..store import store


@dataclass(slots=True)
class ContextStore:
    def load_context(self, project_id: str) -> ContextSnapshot:
        context = store.ensure_audit_context(project_id)
        return ContextSnapshot(
            project_id=project_id,
            context_id=context.id,
            context_version=context.updated_at,
            project_snapshot=context.project_snapshot,
            risk_register=context.risk_register,
            evidence_index=context.evidence_index,
            agent_findings=context.agent_findings,
            open_questions=context.open_questions,
            next_actions=context.next_actions,
        )

    def persist_context(self, project_id: str, payload: SharedAuditContextUpdate | dict[str, Any]) -> ContextSnapshot:
        if isinstance(payload, SharedAuditContextUpdate):
            update_payload = payload
        else:
            update_payload = SharedAuditContextUpdate(
                project_snapshot=payload.get("project_snapshot", {}) if isinstance(payload.get("project_snapshot", {}), dict) else {},
                risk_register=payload.get("risk_register", []) if isinstance(payload.get("risk_register", []), list) else [],
                evidence_index=payload.get("evidence_index", []) if isinstance(payload.get("evidence_index", []), list) else [],
                agent_findings=payload.get("agent_findings", []) if isinstance(payload.get("agent_findings", []), list) else [],
                open_questions=payload.get("open_questions", []) if isinstance(payload.get("open_questions", []), list) else [],
                next_actions=payload.get("next_actions", []) if isinstance(payload.get("next_actions", []), list) else [],
            )
        updated = store.upsert_audit_context(project_id, update_payload)
        return ContextSnapshot(
            project_id=project_id,
            context_id=updated.id,
            context_version=updated.updated_at,
            project_snapshot=updated.project_snapshot,
            risk_register=updated.risk_register,
            evidence_index=updated.evidence_index,
            agent_findings=updated.agent_findings,
            open_questions=updated.open_questions,
            next_actions=updated.next_actions,
        )
