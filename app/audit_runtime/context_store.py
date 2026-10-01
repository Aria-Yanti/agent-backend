from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .audit_md_projection import render_audit_md
from .context_patch import normalize_patch_payload
from .context_state import (
    append_event,
    events_path,
    list_events,
    load_context,
    save_context,
)
from .context_state import context_path as _context_path_for  # noqa: F401  (re-export style import)
from .gate_helpers import find_gate
from .schemas import AuditContextEvent, AuditContextMetadata, AuditContextState
from .trust import evaluate_trust

RUNTIME_AUDIT_MD_ROOT = Path(__file__).resolve().parents[2] / "runtime" / "audit_context"
RUNTIME_AUDIT_MD_ROOT.mkdir(parents=True, exist_ok=True)


def _safe_project_segment(project_id: str) -> str:
    raw = str(project_id or "default").strip() or "default"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)


def audit_md_path(project_id: str) -> Path:
    folder = RUNTIME_AUDIT_MD_ROOT / _safe_project_segment(project_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "Audit.md"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_risk_register(existing: list[dict[str, Any]], updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not updates:
        return list(existing or [])
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in (existing or []):
        key = str(item.get("risk_id") or item.get("risk_code") or item.get("title") or id(item))
        by_key[key] = dict(item)
        order.append(key)
    for item in updates:
        key = str(item.get("risk_id") or item.get("risk_code") or item.get("title") or id(item))
        if key in by_key:
            by_key[key].update({k: v for k, v in item.items() if v not in (None, "")})
        else:
            by_key[key] = dict(item)
            order.append(key)
    return [by_key[key] for key in order]


class AuditContextRuntimeStore:
    def get_or_create_context(self, project_id: str) -> AuditContextState:
        state = load_context(project_id)
        if state is not None:
            return state
        state = AuditContextState(
            context_id=f"auditctxrt_{uuid4().hex[:8]}",
            project_id=project_id,
            version=0,
            metadata=AuditContextMetadata(audit_md_path=str(audit_md_path(project_id))),
        )
        save_context(state)
        return state

    def initialize_context(
        self,
        project_id: str,
        initial_payload: dict[str, Any],
        actor_name: str,
        *,
        misstatement_summary: dict[str, Any] | None = None,
        risk_register: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.clear_runtime(project_id)
        state = self.get_or_create_context(project_id)
        state.version = 1
        state.project_snapshot = dict(initial_payload or {})
        state.misstatement_summary = dict(misstatement_summary or {})
        state.risk_register = list(risk_register or [])
        state.agent_findings = []
        state.next_actions = []
        state.evidence_index = []
        state.review_required_items = []
        state.review_decisions = []
        state.review_gates = []
        state.open_questions = []
        state.skill_calls = []
        state.metadata.last_updated_by = actor_name
        state.metadata.last_updated_at = _utc_now()
        state.metadata.audit_md_path = str(audit_md_path(project_id))
        save_context(state)
        event = AuditContextEvent(
            event_id=f"evt_{uuid4().hex[:10]}",
            context_id=state.context_id,
            project_id=project_id,
            version_before=0,
            version_after=1,
            event_type="context_initialized",
            actor_type="master",
            actor_name=actor_name,
            patch_keys=["planner_init"],
            summary="初始化 Shared Audit Context",
            payload=initial_payload or {},
        )
        append_event(event)
        markdown = render_audit_md(state, list_events(project_id))
        audit_md_path(project_id).write_text(markdown, encoding="utf-8")
        return {
            "context": state,
            "event": event,
            "audit_md": markdown,
            "version_before": 0,
            "version_after": 1,
        }

    def get_latest_context(self, project_id: str) -> AuditContextState:
        return self.get_or_create_context(project_id)

    def read_audit_md(self, project_id: str) -> str:
        path = audit_md_path(project_id)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def apply_patch(
        self,
        project_id: str,
        patch: dict[str, Any],
        actor_name: str,
        task_role: str,
        task_title: str,
    ) -> dict[str, Any]:
        state = self.get_or_create_context(project_id)
        version_before = state.version
        summary_seed = str((patch or {}).get("summary") or "")
        normalized = normalize_patch_payload(patch, actor_name, task_role, summary_seed)

        state.version += 1
        state.agent_findings.extend(list(normalized.get("agent_findings") or []))
        state.next_actions.extend(list(normalized.get("next_actions") or []))
        state.evidence_index.extend(list(normalized.get("evidence_refs") or []))
        state.evidence_index.extend(list(normalized.get("evidence_index_updates") or []))
        state.risk_register = _merge_risk_register(
            state.risk_register,
            list(normalized.get("risk_register_updates") or []),
        )
        state.review_required_items.extend(list(normalized.get("review_required_items") or []))
        state.review_decisions.extend(list(normalized.get("review_decisions") or []))
        state.review_gates.extend(list(normalized.get("review_gates") or []))
        state.open_questions.extend(list(normalized.get("open_questions") or []))
        state.skill_calls.extend(list(normalized.get("skill_calls") or []))
        if normalized.get("misstatement_summary"):
            merged_misstatement = dict(state.misstatement_summary or {})
            merged_misstatement.update(dict(normalized["misstatement_summary"]))
            state.misstatement_summary = merged_misstatement
        state.metadata.last_updated_by = actor_name
        state.metadata.last_updated_at = _utc_now()
        save_context(state)

        patch_keys = [key for key, value in normalized.items() if value]
        event = AuditContextEvent(
            event_id=f"evt_{uuid4().hex[:10]}",
            context_id=state.context_id,
            project_id=project_id,
            version_before=version_before,
            version_after=state.version,
            event_type="agent_patch_applied",
            actor_type="agent",
            actor_name=actor_name,
            task_role=task_role,
            task_title=task_title,
            patch_keys=patch_keys,
            summary=str((normalized.get("agent_findings") or [{}])[-1].get("summary") or "上下文已更新"),
            payload=normalized,
        )
        append_event(event)
        markdown = render_audit_md(state, list_events(project_id))
        audit_md_path(project_id).write_text(markdown, encoding="utf-8")
        return {
            "context": state,
            "event": event,
            "audit_md": markdown,
            "version_before": version_before,
            "version_after": state.version,
        }

    def list_context_events(self, project_id: str) -> list[AuditContextEvent]:
        return list_events(project_id)

    def refresh_trust(self, project_id: str) -> dict[str, Any]:
        state = self.get_or_create_context(project_id)
        result = evaluate_trust(state)
        state.validation_results = list(result.get("validation_results") or [])
        state.trust_score = float(result.get("trust_score") or 0.0)
        save_context(state)
        return {
            "trust_score": state.trust_score,
            "validation_results": state.validation_results,
            "context_version": state.version,
        }

    def detect_pause(self, project_id: str) -> dict[str, Any]:
        """If there are unresolved review_required_items, mark context as paused.

        Provides a semantic pause/resume contract on top of LangGraph's interrupt
        mechanism: the UI can detect ``state.paused`` to know that human review is
        outstanding without inspecting trace events.
        """
        state = self.get_or_create_context(project_id)
        pending = max(len(state.review_required_items) - len(state.review_decisions), 0)
        if pending > 0:
            state.paused = True
            state.pause_step = "人工复核"
            state.pause_reason = f"等待项目经理复核 {pending} 项"
        else:
            state.paused = False
            state.pause_step = ""
            state.pause_reason = ""
        save_context(state)
        return {
            "paused": state.paused,
            "pause_step": state.pause_step,
            "pause_reason": state.pause_reason,
            "pending_review_count": pending,
        }

    def resume(self, project_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        """Clear the paused state and append a review_decisions entry.

        ``decision`` is appended to ``review_decisions`` so the audit trail
        retains a record of who unblocked the workflow and why.
        """
        state = self.get_or_create_context(project_id)
        entry = dict(decision or {})
        entry.setdefault("decision", "approved")
        entry.setdefault("decided_at", _utc_now())
        state.review_decisions.append(entry)
        state.paused = False
        state.pause_step = ""
        state.pause_reason = ""
        save_context(state)
        event = AuditContextEvent(
            event_id=f"evt_{uuid4().hex[:10]}",
            context_id=state.context_id,
            project_id=project_id,
            version_before=state.version,
            version_after=state.version,
            event_type="human_review_decision",
            actor_type="human",
            actor_name=str(entry.get("actor") or "项目经理"),
            task_role="复核",
            task_title="人工复核决策",
            patch_keys=["review_decisions"],
            summary=str(entry.get("comment") or entry.get("decision") or "已审批"),
            payload=entry,
        )
        append_event(event)
        self.refresh_trust(project_id)
        return {
            "paused": state.paused,
            "decision": entry,
            "event": event.model_dump(),
        }

    def build_trail(self, project_id: str) -> list[dict[str, Any]]:
        """Project context events into a human-readable audit trail.

        Each row has ``actor``, ``action``, ``details`` and ``timestamp`` — the
        same four-tuple the audit demo uses, but derived from the existing
        JSONL event log rather than a parallel structure.
        """
        action_labels = {
            "context_initialized": "初始化上下文",
            "agent_context_loaded": "Agent 读取上下文",
            "agent_patch_applied": "Agent 写入上下文",
            "human_review_decision": "人工复核决策",
            "skill_call_recorded": "调用 Skill",
        }
        actor_labels = {
            "master": "Master",
            "agent": "Agent",
            "human": "项目经理",
            "skill": "Skill",
        }
        rows: list[dict[str, Any]] = []
        for event in list_events(project_id):
            actor = f"{actor_labels.get(event.actor_type, event.actor_type)}：{event.actor_name}".strip("：")
            action = action_labels.get(event.event_type, event.event_type)
            detail_parts: list[str] = []
            if event.task_title:
                detail_parts.append(event.task_title)
            if event.patch_keys:
                detail_parts.append("patch=" + ",".join(event.patch_keys))
            if event.summary and event.summary not in detail_parts:
                detail_parts.append(event.summary)
            rows.append({
                "event_id": event.event_id,
                "actor": actor,
                "action": action,
                "details": " | ".join(part for part in detail_parts if part),
                "timestamp": event.created_at,
                "version_after": event.version_after,
            })
        return rows

    def register_review_gate(
        self,
        project_id: str,
        gate: dict[str, Any],
        *,
        actor_name: str = "复核 Agent",
    ) -> dict[str, Any]:
        """Append a HumanReviewGate to the context and record an event.

        Does NOT bump ``state.version`` (the gate is metadata about an existing
        review state, not a context patch). Re-renders Audit.md so the new
        ``## Human Review Gates`` section is visible immediately.
        """
        state = self.get_or_create_context(project_id)
        gate_payload = dict(gate or {})
        gate_payload.setdefault("status", "pending")
        state.review_gates.append(gate_payload)
        state.paused = True
        state.pause_step = "人工复核"
        state.pause_reason = f"等待审计师对 {gate_payload.get('risk_id') or 'A-101'} 复核结论作出决定"
        save_context(state)
        event = AuditContextEvent(
            event_id=f"evt_{uuid4().hex[:10]}",
            context_id=state.context_id,
            project_id=project_id,
            version_before=state.version,
            version_after=state.version,
            event_type="human_review_required",
            actor_type="agent",
            actor_name=actor_name,
            task_role="复核",
            task_title=str(gate_payload.get("title") or "复核 Agent 触发人工复核节点"),
            patch_keys=["review_gates"],
            summary=str(gate_payload.get("ai_recommendation") or "复核 Agent 触发人工复核节点。"),
            payload={"gate": gate_payload},
        )
        append_event(event)
        markdown = render_audit_md(state, list_events(project_id))
        audit_md_path(project_id).write_text(markdown, encoding="utf-8")
        return {
            "context": state,
            "event": event,
            "audit_md": markdown,
            "gate": gate_payload,
            "context_version": state.version,
        }

    def apply_gate_decision(
        self,
        project_id: str,
        gate_id: str,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply a human review decision and bump the context version.

        - Updates the gate dict in-place (``status``, ``reviewer``, ``decided_at``...)
        - Appends a ``review_decisions`` entry
        - Bumps ``state.version`` by 1 (so v9 → v10)
        - Clears pause flags
        - Persists Audit.md
        - Emits a ``human_review_decision`` event
        Returns the updated gate, the decision dict, the new context version
        and the new markdown.
        """
        state = self.get_or_create_context(project_id)
        located = find_gate(state, gate_id)
        if located is None:
            raise ValueError(f"Review gate not found: {gate_id}")
        index, gate_snapshot = located

        decision_kind = str((decision or {}).get("decision") or "approved").strip() or "approved"
        reviewer = str((decision or {}).get("reviewer") or "审计师").strip() or "审计师"
        comment = str((decision or {}).get("comment") or "").strip()
        now = _utc_now()
        context_version_before = state.version
        new_version = state.version + 1

        gate_snapshot["status"] = decision_kind
        gate_snapshot["reviewer"] = reviewer
        gate_snapshot["review_comment"] = comment
        gate_snapshot["decision"] = decision_kind
        gate_snapshot["decided_at"] = now
        gate_snapshot["context_version_after"] = new_version
        state.review_gates[index] = gate_snapshot

        decision_entry = {
            "decision_id": f"dec_{uuid4().hex[:10]}",
            "gate_id": gate_id,
            "project_id": project_id,
            "risk_id": gate_snapshot.get("risk_id") or "A-101",
            "decision": decision_kind,
            "reviewer": reviewer,
            "comment": comment,
            "context_version_before": context_version_before,
            "context_version_after": new_version,
            "created_at": now,
        }
        state.review_decisions.append(decision_entry)

        if decision_kind == "need_more_evidence":
            state.next_actions.append({
                "description": comment or "请补充第三方代付授权文件并扩大函证样本范围。",
                "priority": "high",
                "source": "human_review",
            })
        elif decision_kind == "rejected":
            state.next_actions.append({
                "description": comment or "驳回复核结论，请复核 Agent 重新评估证据并修订结论。",
                "priority": "high",
                "source": "human_review",
            })
        elif decision_kind == "escalated":
            state.next_actions.append({
                "description": comment or "提交项目经理 / 高级审计师复核。",
                "priority": "high",
                "source": "human_review",
            })

        state.version = new_version
        state.paused = False
        state.pause_step = ""
        state.pause_reason = ""
        state.metadata.last_updated_by = reviewer
        state.metadata.last_updated_at = now
        save_context(state)

        event = AuditContextEvent(
            event_id=f"evt_{uuid4().hex[:10]}",
            context_id=state.context_id,
            project_id=project_id,
            version_before=context_version_before,
            version_after=new_version,
            event_type="human_review_decision",
            actor_type="human",
            actor_name=reviewer,
            task_role="复核",
            task_title=str(gate_snapshot.get("title") or "人工复核决策"),
            patch_keys=["review_decisions", "review_gates"],
            summary=comment or f"审计师作出 {decision_kind} 决定。",
            payload={"gate_id": gate_id, "decision": decision_entry, "gate": gate_snapshot},
        )
        append_event(event)
        markdown = render_audit_md(state, list_events(project_id))
        audit_md_path(project_id).write_text(markdown, encoding="utf-8")
        self.refresh_trust(project_id)
        return {
            "gate": gate_snapshot,
            "decision": decision_entry,
            "event": event,
            "audit_md": markdown,
            "context_version_before": context_version_before,
            "context_version_after": new_version,
        }

    def list_review_gates(self, project_id: str) -> list[dict[str, Any]]:
        state = self.get_or_create_context(project_id)
        return [dict(gate) for gate in (state.review_gates or [])]

    def clear_runtime(self, project_id: str) -> None:
        ctx_path = _context_path_for(project_id)
        evt_path = events_path(project_id)
        md_path = audit_md_path(project_id)
        for path in (ctx_path, evt_path, md_path):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass


audit_context_runtime_store = AuditContextRuntimeStore()
