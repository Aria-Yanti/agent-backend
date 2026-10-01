from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .context_renderer import render_context_markdown as _render_context_markdown
from .context_schema import ContextPatch, ContextSnapshot
from .context_store import ContextStore


AUDIT_WORKSPACE_ROOT = Path(__file__).resolve().parents[3] / "audit_context"
AUDIT_MARKDOWN_PATH = AUDIT_WORKSPACE_ROOT / "Audit.md"
AUDIT_EVENTS_PATH = AUDIT_WORKSPACE_ROOT / "audit_events.jsonl"



def _normalize_context_patch_items(items: Any, *, item_type: str) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            normalized.append(item)
            continue
        if item is None:
            continue
        text = str(item).strip()
        if not text:
            continue
        if item_type == "next_actions":
            normalized.append({"description": text, "status": "open", "source": "agent"})
        else:
            normalized.append({"description": text, "source": "agent"})
    return normalized



def _normalize_context_patch_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized["next_actions"] = _normalize_context_patch_items(normalized.get("next_actions", []), item_type="next_actions")
    normalized["risk_register_updates"] = _normalize_context_patch_items(normalized.get("risk_register_updates", []), item_type="risk_register_updates")
    normalized["evidence_refs"] = _normalize_context_patch_items(normalized.get("evidence_refs", []), item_type="evidence_refs")
    normalized["agent_findings"] = _normalize_context_patch_items(normalized.get("agent_findings", []), item_type="agent_findings")
    normalized["open_questions"] = _normalize_context_patch_items(normalized.get("open_questions", []), item_type="open_questions")
    normalized["risk_status_updates"] = _normalize_context_patch_items(normalized.get("risk_status_updates", []), item_type="risk_status_updates")
    return normalized



def _ensure_workspace_files() -> None:
    AUDIT_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    if not AUDIT_MARKDOWN_PATH.exists():
        AUDIT_MARKDOWN_PATH.write_text("# Audit Shared Context v0\n\n", encoding="utf-8")
    if not AUDIT_EVENTS_PATH.exists():
        AUDIT_EVENTS_PATH.write_text("", encoding="utf-8")


class AuditContextManager:
    def __init__(self) -> None:
        self._store = ContextStore()

    def load_context(self, project_id: str) -> ContextSnapshot:
        return self._store.load_context(project_id)

    def get_latest_context(self, project_id: str) -> ContextSnapshot:
        return self.load_context(project_id)

    def render_context_markdown(self, project_id: str) -> str:
        return _render_context_markdown(self.load_context(project_id))

    def readAuditContext(self) -> str:
        _ensure_workspace_files()
        return AUDIT_MARKDOWN_PATH.read_text(encoding="utf-8")

    def appendAuditContext(self, agentName: str, taskId: str, markdownBlock: str, eventJson: dict[str, Any]) -> None:
        _ensure_workspace_files()
        block = str(markdownBlock or "").strip()
        if block:
            with AUDIT_MARKDOWN_PATH.open("a", encoding="utf-8") as handle:
                handle.write(f"\n\n{block}\n")
        event_payload = dict(eventJson or {})
        event_payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        event_payload.setdefault("agent_name", agentName)
        event_payload.setdefault("task_id", taskId)
        with AUDIT_EVENTS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event_payload, ensure_ascii=False) + "\n")

    def clearAuditWorkspace(self) -> dict[str, object]:
        _ensure_workspace_files()
        AUDIT_MARKDOWN_PATH.write_text("# Audit Shared Context v0\n\n", encoding="utf-8")
        AUDIT_EVENTS_PATH.write_text("", encoding="utf-8")
        return {"content": self.readAuditContext(), "events": []}

    def initializeAuditContext(self, title: str = "# Audit Shared Context v1") -> str:
        _ensure_workspace_files()
        content = str(title or "# Audit Shared Context v1").strip() + "\n\n"
        AUDIT_MARKDOWN_PATH.write_text(content, encoding="utf-8")
        return content

    def write_rendered_audit_context(self, markdown: str) -> None:
        _ensure_workspace_files()
        AUDIT_MARKDOWN_PATH.write_text(str(markdown or "").strip() + "\n", encoding="utf-8")

    def getAuditEvents(self) -> list[dict[str, Any]]:
        _ensure_workspace_files()
        events: list[dict[str, Any]] = []
        for line in AUDIT_EVENTS_PATH.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
        return events

    def build_markdown_from_snapshot(self, snapshot: ContextSnapshot) -> str:
        version = str(snapshot.context_version or "")
        project_snapshot = snapshot.project_snapshot or {}
        analysis_summary = project_snapshot.get("analysis_summary", {}) if isinstance(project_snapshot, dict) else {}
        expected_comparison = project_snapshot.get("expected_comparison", {}) if isinstance(project_snapshot, dict) else {}
        exception_candidates = project_snapshot.get("exception_candidates", []) if isinstance(project_snapshot, dict) else []
        findings = snapshot.agent_findings or []
        review_required_items = []
        next_actions = snapshot.next_actions or []

        lines = [
            f"# Audit Shared Context v{version}",
            "",
            "## 当前风险",
            "A-101 收入虚增——第三方代付",
            "",
            "## 最新发现",
        ]
        for item in findings[-6:]:
            lines.append(f"- {item.get('agent_name', 'agent')}: {item.get('summary', '')}")
        if len(lines) == 6:
            lines.append("- 暂无发现")

        lines.extend(["", "## 风险登记"])
        for item in snapshot.risk_register[-10:]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('risk_id') or item.get('risk_code') or 'A-101'} | {item.get('status', '')} | {item.get('title', item.get('summary', ''))}")
        if lines[-1] == "## 风险登记":
            lines.append("- 暂无风险登记更新")

        lines.extend(["", "## 证据引用"])
        for item in snapshot.evidence_index[-10:]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('file_name') or item.get('evidence_code') or item}")
        if lines[-1] == "## 证据引用":
            lines.append("- 暂无证据引用")

        lines.extend(["", "## 后续动作"])
        for item in next_actions[:10]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('description', '')}")
            else:
                lines.append(f"- {item}")
        if lines[-1] == "## 后续动作":
            lines.append("- 暂无后续动作")

        lines.extend(["", "## 人工复核"])
        for item in review_required_items[:10]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('title', '')}: {item.get('reason', '')}")
        if lines[-1] == "## 人工复核":
            lines.append("- 暂无人工复核事项")

        if expected_comparison:
            lines.extend([
                "",
                "## 关键指标",
                f"- detected_exception_count: {expected_comparison.get('detected_exception_count', 0)}",
                f"- detected_high_risk_amount: {expected_comparison.get('detected_high_risk_amount', 0)}",
            ])
        if exception_candidates:
            lines.extend(["", "## 样本异常摘录"])
            for item in exception_candidates[:5]:
                lines.append(f"- {item.get('revenue_id', '')} | {item.get('contract_no', '')} | {item.get('amount', 0)} | {item.get('payer_name', '')}")
        if analysis_summary:
            lines.extend(["", "## 分析摘要"])
            lines.append(json.dumps(analysis_summary, ensure_ascii=False))

        return "\n".join(lines)

    def apply_context_patch(self, project_id: str, agent_name: str, patch_json: dict[str, Any]) -> dict[str, Any]:
        current = self.load_context(project_id)
        patch = ContextPatch.model_validate(_normalize_context_patch_payload(patch_json or {}))

        project_snapshot = dict(current.project_snapshot)
        project_snapshot.update(patch.project_snapshot)

        risk_register = list(current.risk_register)
        if patch.risk_register_updates:
            risk_register.extend(patch.risk_register_updates)

        evidence_index = list(current.evidence_index)
        if patch.evidence_refs:
            evidence_index.extend(patch.evidence_refs)

        agent_findings = list(current.agent_findings)
        if patch.agent_findings:
            for finding in patch.agent_findings:
                merged = dict(finding)
                merged.setdefault("agent_name", agent_name)
                merged.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                agent_findings.append(merged)

        open_questions = list(current.open_questions)
        if patch.open_questions:
            open_questions.extend(patch.open_questions)

        next_actions = list(current.next_actions)
        if patch.next_actions:
            next_actions.extend(patch.next_actions)

        for update in patch.risk_status_updates:
            risk_id = str(update.get("risk_id") or "").strip()
            status = str(update.get("status") or "").strip()
            if not (risk_id and status):
                continue
            for item in risk_register:
                if str(item.get("risk_id") or "").strip() == risk_id:
                    item["status"] = status

        updated = self._store.persist_context(
            project_id,
            {
                "project_snapshot": project_snapshot,
                "risk_register": risk_register,
                "evidence_index": evidence_index,
                "agent_findings": agent_findings,
                "open_questions": open_questions,
                "next_actions": next_actions,
            },
        )

        patch_keys = [key for key, value in (patch_json or {}).items() if value]
        history_item = {
            "version": updated.context_version,
            "updated_by": agent_name,
            "summary": (patch.agent_findings[-1].get("summary") if patch.agent_findings else "") or "上下文已更新",
            "patch_keys": patch_keys,
        }
        self.appendAuditContext(agent_name, f"context-{updated.context_version}", "", history_item)
        return {
            "context_id": updated.context_id,
            "context_version_before": current.context_version,
            "context_version_after": updated.context_version,
            "updated_by": agent_name,
            "patch_keys": patch_keys,
            "markdown": self.readAuditContext(),
            "history_item": history_item,
            "snapshot": updated,
        }

    def append_agent_finding(self, project_id: str, agent_name: str, finding: dict[str, Any]) -> dict[str, Any]:
        return self.apply_context_patch(
            project_id,
            agent_name,
            {"agent_findings": [finding]},
        )

    def update_risk_status(self, project_id: str, risk_id: str, status: str) -> dict[str, Any]:
        return self.apply_context_patch(
            project_id,
            "system",
            {"risk_status_updates": [{"risk_id": risk_id, "status": status}]},
        )

    def add_evidence_ref(self, project_id: str, evidence_item: dict[str, Any]) -> dict[str, Any]:
        return self.apply_context_patch(
            project_id,
            "system",
            {"evidence_refs": [evidence_item]},
        )

    def create_context_snapshot(self, project_id: str) -> dict[str, Any]:
        snapshot = self.load_context(project_id)
        return json.loads(snapshot.model_dump_json())


audit_context_manager = AuditContextManager()
