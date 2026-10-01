from __future__ import annotations

from typing import Any

from .schemas import AuditContextEvent, AuditContextState


def _fmt_amount(amount: Any) -> str:
    try:
        value = int(amount or 0)
    except (TypeError, ValueError):
        return str(amount or "—")
    return f"{value:,}"


def _fmt_list(items: list[Any]) -> str:
    if not items:
        return "—"
    parts = [str(item) for item in items if str(item or "").strip()]
    return " / ".join(parts) if parts else "—"


def _summarize_project_snapshot(snapshot: dict[str, Any]) -> dict[str, str]:
    analysis = snapshot.get("analysis_summary") or {}
    expected = snapshot.get("expected_comparison") or {}
    project_name = (
        analysis.get("project_name")
        or analysis.get("project")
        or snapshot.get("project_name")
        or "AuditBrain A-101 测试包"
    )
    audit_period = (
        analysis.get("audit_period")
        or analysis.get("period")
        or snapshot.get("audit_period")
        or "—"
    )
    exception_count = (
        analysis.get("exception_count")
        or expected.get("detected_exception_count")
        or len(snapshot.get("exception_candidates") or [])
        or 0
    )
    high_risk_amount = (
        analysis.get("high_risk_amount")
        or expected.get("detected_high_risk_amount")
        or 0
    )
    return {
        "project_name": str(project_name),
        "audit_period": str(audit_period),
        "exception_count": str(exception_count),
        "high_risk_amount": _fmt_amount(high_risk_amount),
    }


def _render_risk_table(risk_register: list[dict[str, Any]]) -> list[str]:
    if not risk_register:
        return ["- 暂无登记风险"]
    lines = [
        "| 风险编号 | 名称 | 等级 | 涉及科目 | 涉及认定 | 状态 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in risk_register:
        risk_id = str(item.get("risk_id") or item.get("risk_code") or "—")
        title = str(item.get("title") or item.get("name") or "—")
        level = str(item.get("risk_level") or item.get("level") or "—")
        accounts = _fmt_list(list(item.get("related_accounts") or item.get("accounts") or []))
        assertions = _fmt_list(list(item.get("assertions") or []))
        status = str(item.get("status") or "open")
        lines.append(f"| {risk_id} | {title} | {level} | {accounts} | {assertions} | {status} |")
    return lines


def _render_evidence_list(evidence_index: list[Any]) -> list[str]:
    if not evidence_index:
        return ["- 暂无证据引用"]
    lines: list[str] = []
    seen: set[str] = set()
    for item in evidence_index:
        if isinstance(item, dict):
            code = str(item.get("evidence_code") or item.get("code") or "").strip()
            name = str(item.get("file_name") or item.get("name") or item.get("description") or "").strip()
            label = " ".join(part for part in (code, name) if part) or str(item)
        else:
            label = str(item).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        lines.append(f"- {label}")
    if not lines:
        return ["- 暂无证据引用"]
    return lines


def _render_next_actions(next_actions: list[dict[str, Any]]) -> list[str]:
    if not next_actions:
        return ["- 暂无后续程序"]
    lines: list[str] = []
    for item in next_actions:
        description = str(item.get("description") or item.get("title") or item or "—").strip()
        priority = str(item.get("priority") or "medium").strip() or "medium"
        if not description:
            continue
        lines.append(f"- [{priority}] {description}")
    return lines or ["- 暂无后续程序"]


def _render_review_required(review_required_items: list[dict[str, Any]]) -> list[str]:
    if not review_required_items:
        return ["- 暂无人工复核事项"]
    lines: list[str] = []
    for item in review_required_items:
        description = str(item.get("description") or item.get("title") or item or "—").strip()
        owner = str(item.get("owner") or item.get("assignee") or "").strip()
        if not description:
            continue
        suffix = f"（负责人：{owner}）" if owner else ""
        lines.append(f"- {description}{suffix}")
    return lines or ["- 暂无人工复核事项"]


def _render_agent_findings_by_event(events: list[AuditContextEvent]) -> list[str]:
    patch_events = [event for event in events if event.event_type == "agent_patch_applied"]
    if not patch_events:
        return ["- 暂无 Agent 写入"]
    lines: list[str] = []
    for event in patch_events:
        actor = event.actor_name or "Agent"
        version_label = f"v{event.version_after}"
        lines.append(f"### {version_label} · {actor}")
        if event.task_title:
            lines.append(f"> 任务：{event.task_title}")
        if event.patch_keys:
            lines.append(f"> patch_keys: {', '.join(event.patch_keys)}")
        summary = (event.summary or "").strip() or "（无摘要）"
        lines.append("")
        lines.append(summary)
        lines.append("")
    return lines


def _render_context_history(events: list[AuditContextEvent]) -> list[str]:
    if not events:
        return ["- 暂无写入历史"]
    lines = [
        "| 版本 | 时间 | 写入者 | 类型 | patch_keys |",
        "| --- | --- | --- | --- | --- |",
    ]
    for event in events:
        version_label = f"v{event.version_after}"
        created = (event.created_at or "").replace("T", " ").split(".")[0]
        actor = event.actor_name or "—"
        type_label = event.event_type
        patch_label = ", ".join(event.patch_keys) if event.patch_keys else "(init)"
        lines.append(f"| {version_label} | {created} | {actor} | {type_label} | {patch_label} |")
    return lines


def render_audit_md(context_state: AuditContextState, events: list[AuditContextEvent]) -> str:
    snapshot_info = _summarize_project_snapshot(context_state.project_snapshot or {})
    misstatement = context_state.misstatement_summary or {}

    lines: list[str] = []
    lines.append(f"# Audit Shared Context v{context_state.version}")
    last_by = context_state.metadata.last_updated_by or "—"
    last_at = (context_state.metadata.last_updated_at or "").replace("T", " ").split(".")[0]
    lines.append("")
    lines.append(f"> 最后写入：**{last_by}** · {last_at or '—'}")
    lines.append("")

    lines.append("## Project Snapshot")
    lines.append(f"- 项目：{snapshot_info['project_name']}")
    lines.append(f"- 审计期间：{snapshot_info['audit_period']}")
    lines.append("- 当前风险：A-101 收入虚增——第三方代付")
    lines.append("")

    lines.append("## Current Risk")
    lines.append("A-101 收入虚增——第三方代付")
    lines.append("")

    lines.append("## Sample Data Analysis")
    project_snapshot = context_state.project_snapshot or {}
    analysis_summary = project_snapshot.get("analysis_summary") or {}
    expected = project_snapshot.get("expected_comparison") or {}
    warnings = project_snapshot.get("data_quality_warnings") or []
    exception_candidates = project_snapshot.get("exception_candidates") or []
    detected_count = (
        expected.get("detected_exception_count")
        or analysis_summary.get("detected_exception_count")
        or len(exception_candidates)
        or 0
    )
    high_risk_amount = (
        expected.get("detected_high_risk_amount")
        or analysis_summary.get("detected_high_risk_amount")
        or analysis_summary.get("high_risk_amount")
        or 0
    )
    evidence_total = len(context_state.evidence_index or [])
    lines.append(f"- 异常交易数量：{detected_count}")
    lines.append(f"- 疑似错报金额：{_fmt_amount(high_risk_amount)}")
    lines.append(f"- 证据覆盖：共索引 {evidence_total} 份证据文件")
    lines.append(f"- 数据质量提示：{len(warnings)} 条")
    rule_engine = analysis_summary.get("rule_engine_version") or analysis_summary.get("engine_version")
    if rule_engine:
        lines.append(f"- 规则引擎版本：{rule_engine}")
    lines.append("")

    lines.append("## Misstatement Summary")
    if misstatement:
        amount = _fmt_amount(misstatement.get("suspected_amount"))
        count = misstatement.get("exception_count")
        accounts = _fmt_list(list(misstatement.get("affected_accounts") or []))
        lines.append(f"- 疑似错报金额：{amount}")
        lines.append(f"- 异常交易数量：{count if count is not None else '—'}")
        lines.append(f"- 涉及科目：{accounts}")
    else:
        lines.append("- 暂无错报汇总")
    lines.append("")

    lines.append("## Risk Register")
    lines.extend(_render_risk_table(context_state.risk_register or []))
    lines.append("")

    lines.append("## Agent Findings")
    lines.extend(_render_agent_findings_by_event(events or []))

    lines.append("## Evidence References")
    lines.extend(_render_evidence_list(context_state.evidence_index or []))
    lines.append("")

    lines.append("## Next Actions")
    lines.extend(_render_next_actions(context_state.next_actions or []))
    lines.append("")

    lines.append("## Review Required")
    lines.extend(_render_review_required(context_state.review_required_items or []))
    lines.append("")

    review_gates = list(getattr(context_state, "review_gates", []) or [])
    if review_gates:
        lines.append("## Human Review Gates")
        for gate in review_gates:
            if not isinstance(gate, dict):
                continue
            title = str(gate.get("title") or gate.get("gate_id") or "Human Review Gate")
            status = str(gate.get("status") or "pending")
            required_role = str(gate.get("required_role") or "—")
            ai_rec = str(gate.get("ai_recommendation") or "").strip()
            risk_id = str(gate.get("risk_id") or "—")
            suspected = _fmt_amount(gate.get("suspected_amount"))
            exception_count = gate.get("exception_count")
            lines.append(f"### {title}")
            lines.append(f"- 状态：**{status}**")
            lines.append(f"- 风险编号：{risk_id}")
            lines.append(f"- 疑似错报金额：{suspected}")
            lines.append(f"- 异常交易数量：{exception_count if exception_count is not None else '—'}")
            lines.append(f"- 复核角色：{required_role}")
            if ai_rec:
                lines.append(f"- AI 复核建议：{ai_rec}")
            review_items = list(gate.get("review_items") or [])
            if review_items:
                lines.append("- 复核问题：")
                for item in review_items:
                    question = str((item or {}).get("question") or "").strip()
                    if question:
                        lines.append(f"  - {question}")
            lines.append("")

    review_decisions = list(getattr(context_state, "review_decisions", []) or [])
    if review_decisions:
        lines.append("## Human Review Decisions")
        decision_label = {
            "approved": "已批准",
            "need_more_evidence": "要求补充证据",
            "rejected": "已驳回",
            "escalated": "已提交项目经理",
        }
        for item in review_decisions:
            if not isinstance(item, dict):
                description = str(item or "—").strip()
                if description:
                    lines.append(f"- {description}")
                continue
            version_after = item.get("context_version_after")
            decision_kind = str(item.get("decision") or "").strip()
            human_label = decision_label.get(decision_kind, decision_kind or "—")
            reviewer = str(item.get("reviewer") or "审计师").strip() or "审计师"
            comment = str(item.get("comment") or "").strip()
            risk_id = str(item.get("risk_id") or "A-101").strip()
            decided_at = (item.get("created_at") or "").replace("T", " ").split(".")[0]
            heading = f"### v{version_after} · Human Review Decision" if version_after else "### Human Review Decision"
            lines.append(heading)
            lines.append(f"{reviewer}对 {risk_id} 复核结论作出 **{human_label}** 决定。")
            lines.append("")
            lines.append(f"- 决定：{decision_kind or '—'}")
            lines.append(f"- 审核人：{reviewer}")
            if comment:
                lines.append(f"- 意见：{comment}")
            if decided_at:
                lines.append(f"- 决策时间：{decided_at}")
            lines.append("")

    if context_state.open_questions:
        lines.append("## Open Questions")
        for item in context_state.open_questions:
            description = str(item.get("description") or item.get("question") or item or "—").strip()
            if description:
                lines.append(f"- {description}")
        lines.append("")

    lines.append("## Context History")
    lines.extend(_render_context_history(events or []))
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
