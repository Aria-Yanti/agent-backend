from __future__ import annotations

from typing import Any

from .context_schema import ContextSnapshot



def _format_amount(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return str(value or 0)
    return f"{amount:,.0f}"



def _format_jsonish_list(items: list[Any], *, limit: int = 10) -> list[Any]:
    return list(items[:limit]) if items else []



def _extract_a101_analysis(snapshot: ContextSnapshot) -> dict[str, Any]:
    project_snapshot = snapshot.project_snapshot or {}
    return {
        "analysis_summary": project_snapshot.get("analysis_summary", {}),
        "exception_candidates": project_snapshot.get("exception_candidates", []),
        "expected_comparison": project_snapshot.get("expected_comparison", {}),
        "evidence_index": project_snapshot.get("evidence_index", snapshot.evidence_index or []),
        "data_quality_warnings": project_snapshot.get("data_quality_warnings", []),
    }



def _render_a101_analysis(snapshot: ContextSnapshot) -> list[str]:
    analysis = _extract_a101_analysis(snapshot)
    analysis_summary = analysis["analysis_summary"] if isinstance(analysis["analysis_summary"], dict) else {}
    exception_candidates = analysis["exception_candidates"] if isinstance(analysis["exception_candidates"], list) else []
    expected_comparison = analysis["expected_comparison"] if isinstance(analysis["expected_comparison"], dict) else {}
    evidence_index = analysis["evidence_index"] if isinstance(analysis["evidence_index"], list) else []
    data_quality_warnings = analysis["data_quality_warnings"] if isinstance(analysis["data_quality_warnings"], list) else []

    if not any([analysis_summary, exception_candidates, expected_comparison, evidence_index, data_quality_warnings]):
        return []

    related_file_names = {
        str(ref.get("file_name") or "")
        for candidate in exception_candidates
        for ref in list(candidate.get("evidence_refs") or [])
        if isinstance(ref, dict)
    }
    filtered_evidence = [item for item in evidence_index if str(item.get("file_name") or "") in related_file_names][:10]

    lines: list[str] = [
        "",
        "## A-101 Sample Data Analysis",
        "",
        "### Analysis Summary",
        f"- detected_exception_count: {expected_comparison.get('detected_exception_count', analysis_summary.get('exception_candidate_count', 0))}",
        f"- detected_high_risk_amount: {_format_amount(expected_comparison.get('detected_high_risk_amount', analysis_summary.get('detected_high_risk_amount', 0)))}",
        f"- expected_exception_count: {expected_comparison.get('expected_exception_count', 0)}",
        f"- expected_high_risk_amount: {_format_amount(expected_comparison.get('expected_high_risk_amount', 0))}",
        f"- evidence_coverage_rate: {expected_comparison.get('evidence_coverage_rate', 0)}",
        f"- data_quality_warnings_count: {len(data_quality_warnings)}",
        "",
        "### Exception Candidates",
    ]

    for candidate in exception_candidates[:10]:
        evidence_refs = [str(ref.get("file_name") or "") for ref in list(candidate.get("evidence_refs") or []) if isinstance(ref, dict)]
        lines.extend(
            [
                f"- revenue_id: {candidate.get('revenue_id', '')}",
                f"  - contract_no: {candidate.get('contract_no', '')}",
                f"  - invoice_no: {candidate.get('invoice_no', '')}",
                f"  - customer_name: {candidate.get('customer_name', '')}",
                f"  - payer_name: {candidate.get('payer_name', '')}",
                f"  - amount: {_format_amount(candidate.get('amount', 0))}",
                f"  - exception_type: {candidate.get('exception_type', '')}",
                f"  - risk_level: {candidate.get('risk_level', '')}",
                f"  - reason: {candidate.get('reason', '')}",
                f"  - evidence_refs: {', '.join(evidence_refs) if evidence_refs else '(none)'}",
            ]
        )

    lines.extend(
        [
            "",
            "### Expected Comparison",
            f"- matched_exception_count: {expected_comparison.get('matched_exception_count', 0)}",
            f"- missed_exception_count: {expected_comparison.get('missed_exception_count', 0)}",
            f"- false_positive_count: {expected_comparison.get('false_positive_count', 0)}",
            f"- amount_difference: {_format_amount(expected_comparison.get('amount_difference', 0))}",
            "",
            "### Evidence Index",
        ]
    )

    for item in filtered_evidence:
        lines.append(
            f"- {item.get('file_name', '')} | type={item.get('evidence_type', '')} | path={item.get('relative_path', '')}"
        )

    lines.extend(["", "### Data Quality Warnings"])
    if data_quality_warnings:
        for warning in _format_jsonish_list(data_quality_warnings, limit=10):
            lines.append(
                f"- revenue_id={warning.get('revenue_id', '')}; field={warning.get('field', '')}; warning={warning.get('warning', '')}"
            )
    else:
        lines.append("- (none)")

    return lines



def render_context_markdown(snapshot: ContextSnapshot) -> str:
    lines: list[str] = [
        "# Shared Audit Context",
        f"- Project ID: {snapshot.project_id}",
        f"- Context ID: {snapshot.context_id or '(none)'}",
        f"- Context Version: {snapshot.context_version}",
        "",
        "## Project Snapshot",
        str(snapshot.project_snapshot or {}),
        "",
        "## Risk Register",
        str(snapshot.risk_register or []),
        "",
        "## Evidence Index",
        str(snapshot.evidence_index or []),
        "",
        "## Agent Findings",
        str(snapshot.agent_findings or []),
        "",
        "## Open Questions",
        str(snapshot.open_questions or []),
        "",
        "## Next Actions",
        str(snapshot.next_actions or []),
    ]
    lines.extend(_render_a101_analysis(snapshot))
    return "\n".join(lines)
