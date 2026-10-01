"""Trust / validation layer for audit shared context.

Ported from the demo `audit/audit/backend/app/core/trust_ai.py`,
adapted to the main project's `AuditContextState` schema.

Produces:
- validate_risk(risk, evidence_index): per-risk evidence sufficiency check
- check_output(state): six-dimension output health check, returns a list of {category, status, message}
- calculate_trust_score(state): aggregates check results into a 0-1 float

All pure functions — no I/O, no external dependencies.
"""
from __future__ import annotations

from typing import Any


def _evidence_for_risk(risk: dict[str, Any], evidence_index: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risk_id = str(risk.get("risk_id") or risk.get("risk_code") or "").strip()
    related: list[dict[str, Any]] = []
    for item in evidence_index or []:
        if not isinstance(item, dict):
            continue
        ev_risk = str(item.get("risk_id") or "").strip()
        if not ev_risk:
            related.append(item)
        elif risk_id and ev_risk == risk_id:
            related.append(item)
    return related


def validate_risk(risk: dict[str, Any], evidence_index: list[dict[str, Any]]) -> dict[str, Any]:
    risk_id = str(risk.get("risk_id") or risk.get("risk_code") or "").strip()
    level_raw = str(risk.get("risk_level") or risk.get("level") or "low").strip()
    level_norm = level_raw.lower()
    if level_raw in ("高", "高风险"):
        level_norm = "high"
    elif level_raw in ("中", "中风险"):
        level_norm = "medium"
    elif level_raw in ("低", "低风险"):
        level_norm = "low"

    title = str(risk.get("title") or risk.get("summary") or "")
    related = _evidence_for_risk(risk, evidence_index)

    issues: list[str] = []
    valid = True
    if level_norm == "high" and len(related) < 2:
        valid = False
        issues.append(f"高风险缺少证据链，当前只有 {len(related)} 份证据")
    if level_norm == "medium" and len(related) < 1:
        valid = False
        issues.append(f"中风险缺少证据，当前只有 {len(related)} 份证据")

    evidence_types = {str(item.get("type") or item.get("evidence_type") or "") for item in related}
    if len(related) >= 2 and len(evidence_types - {""}) < 2:
        issues.append("证据类型较为单一，建议补充其他类型证据")

    return {
        "risk_id": risk_id,
        "risk_title": title,
        "level": level_norm,
        "evidence_count": len(related),
        "valid": valid,
        "issues": issues,
    }


def check_output(state: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    risk_register = list(getattr(state, "risk_register", []) or [])
    if not risk_register:
        results.append({"category": "风险登记册", "status": "warning", "message": "风险登记册为空"})
    else:
        results.append({"category": "风险登记册", "status": "ok", "message": f"共识别到 {len(risk_register)} 条风险"})

    evidence_index = list(getattr(state, "evidence_index", []) or [])
    if not evidence_index:
        results.append({"category": "证据索引", "status": "warning", "message": "证据索引为空"})
    else:
        results.append({"category": "证据索引", "status": "ok", "message": f"共收集到 {len(evidence_index)} 份证据"})

    for risk in risk_register:
        rv = validate_risk(risk, evidence_index)
        results.append({
            "category": "风险证据校验",
            "risk_id": rv["risk_id"],
            "risk_title": rv["risk_title"],
            "status": "ok" if rv["valid"] else "error",
            "message": "；".join(rv["issues"]) if rv["issues"] else "校验通过",
        })

    misstatement = dict(getattr(state, "misstatement_summary", {}) or {})
    if not misstatement.get("suspected_amount") and not misstatement.get("affected_accounts"):
        results.append({"category": "错报汇总", "status": "warning", "message": "错报汇总尚未生成"})
    else:
        amount = misstatement.get("suspected_amount", 0)
        accounts = misstatement.get("affected_accounts") or []
        results.append({
            "category": "错报汇总",
            "status": "ok",
            "message": f"疑似错报 {amount}，涉及科目 {len(accounts)} 项",
        })

    review_items = list(getattr(state, "review_required_items", []) or [])
    review_decisions = list(getattr(state, "review_decisions", []) or [])
    if not review_items and not review_decisions:
        results.append({"category": "人工复核", "status": "warning", "message": "未进行人工复核"})
    else:
        pending = len(review_items) - len(review_decisions)
        if pending > 0:
            results.append({"category": "人工复核", "status": "warning", "message": f"存在 {pending} 条待复核项"})
        else:
            results.append({"category": "人工复核", "status": "ok", "message": "所有复核项已完成"})

    findings = list(getattr(state, "agent_findings", []) or [])
    if not findings:
        results.append({"category": "可解释性", "status": "warning", "message": "缺少 Agent 推理过程记录"})
    else:
        results.append({"category": "可解释性", "status": "ok", "message": f"已记录 {len(findings)} 条 Agent 写入"})

    return results


def calculate_trust_score(state: Any) -> float:
    risk_register = list(getattr(state, "risk_register", []) or [])
    evidence_index = list(getattr(state, "evidence_index", []) or [])
    review_items = list(getattr(state, "review_required_items", []) or [])
    review_decisions = list(getattr(state, "review_decisions", []) or [])
    misstatement = dict(getattr(state, "misstatement_summary", {}) or {})

    scores: list[float] = []

    if risk_register:
        valid_count = sum(1 for r in risk_register if validate_risk(r, evidence_index)["valid"])
        scores.append(valid_count / len(risk_register))
    else:
        scores.append(0.5)

    if risk_register and evidence_index:
        avg = len(evidence_index) / len(risk_register)
        scores.append(min(avg / 3.0, 1.0))
    else:
        scores.append(0.5)

    if review_items:
        scores.append(len(review_decisions) / len(review_items) if review_items else 0.0)
    else:
        scores.append(0.5)

    if misstatement.get("suspected_amount") and misstatement.get("affected_accounts"):
        scores.append(0.9)
    else:
        scores.append(0.5)

    return round(sum(scores) / len(scores), 3) if scores else 0.0


def evaluate_trust(state: Any) -> dict[str, Any]:
    """Convenience wrapper: returns both validation_results and trust_score."""
    return {
        "validation_results": check_output(state),
        "trust_score": calculate_trust_score(state),
    }
