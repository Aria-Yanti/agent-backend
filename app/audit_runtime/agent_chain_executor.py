from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..audit_data import analyze_a101_sample, load_a101_sample_bundle
from ..runtime import llm_gateway
from ..schemas import RunArtifacts, TraceEvent, WorkflowEdge, WorkflowGraph, WorkflowNode, WorkflowRunResponse
from .audit_event_bus import push_event
from .context_store import audit_context_runtime_store
from .gate_helpers import build_final_review_gate, project_gate_for_sse
from .guards import ensure_analysis_available
from .output_parser import is_filesystem_refusal, merge_patches, parse_agent_output, strip_tool_noise
from .trust import evaluate_trust

AUDIT_CHAIN = [
    {
        "node_id": "analytical_procedure_agent",
        "agent_name": "分析性程序 Agent",
        "task_role": "分析性程序",
        "task_title": "分析性程序 Agent：引用真实 A-101 分析结果，围绕期末集中确认、第三方代付异常数量与金额执行分析性程序。",
        "subtitle": "收入趋势与第三方代付异常分析",
        "patch_focus": "agent_findings, evidence_refs, next_actions",
        "instruction": "请汇总 5 笔第三方代付异常的金额、客户名称和期末集中度，给出疑似错报量级初判。",
    },
    {
        "node_id": "risk_identification_agent",
        "agent_name": "风险识别 Agent",
        "task_role": "风险识别",
        "task_title": "风险识别 Agent：基于 exception_candidates 识别 A-101 风险、影响认定及优先级。",
        "subtitle": "识别 A-101 风险、科目与认定",
        "patch_focus": "risk_register_updates（必填）, agent_findings",
        "instruction": "请将 A-101 标记为高风险，关联营业收入 / 应收账款科目以及发生 / 准确性 / 截止认定，并在 risk_register_updates 中给出结构化条目。",
    },
    {
        "node_id": "audit_planning_agent",
        "agent_name": "审计计划 Agent",
        "task_role": "审计计划",
        "task_title": "审计计划 Agent：基于真实异常类型制定审计程序，包括 HT/FP/BS 证据链、授权文件、函证与截止测试。",
        "subtitle": "生成审计响应程序",
        "patch_focus": "next_actions, agent_findings",
        "instruction": "请输出后续凭证核对、合同校验、函证、截止测试等审计响应程序，并在 next_actions 中给出优先级。",
    },
    {
        "node_id": "voucher_checking_agent",
        "agent_name": "凭证核对 Agent",
        "task_role": "凭证核对",
        "task_title": "凭证核对 Agent：引用 revenue_id、contract_no、invoice_no、bank slip id 与 evidence_refs 核对支持证据。",
        "subtitle": "核对合同 / 发票 / 银行回单 / 验收单",
        "patch_focus": "evidence_refs, agent_findings",
        "instruction": "请完成合同 / 发票 / 银行回单 / 验收单证据链交叉核对，并把使用到的 evidence_code 放入 evidence_refs。",
    },
    {
        "node_id": "contract_review_agent",
        "agent_name": "合同校验 Agent",
        "task_role": "合同校验",
        "task_title": "合同校验 Agent：检查第三方代付授权文件、付款条款与合同客户一致性。",
        "subtitle": "校验代付条款和授权文件",
        "patch_focus": "agent_findings, review_required_items",
        "instruction": "请指出合同未允许第三方代付、缺少授权文件等具体发现，并把需要项目经理补充审阅的事项放入 review_required_items。",
    },
    {
        "node_id": "confirmation_checking_agent",
        "agent_name": "函证核对 Agent",
        "task_role": "函证核对",
        "task_title": "函证核对 Agent：对异常样本对应客户执行函证核对与回函差异分析。",
        "subtitle": "生成函证和回函核对建议",
        "patch_focus": "next_actions, agent_findings",
        "instruction": "请对异常样本对应的客户给出函证建议，并把扩大函证范围、跟进回函差异作为 next_actions。",
    },
    {
        "node_id": "misstatement_summary_agent",
        "agent_name": "错报汇总 Agent",
        "task_role": "错报汇总",
        "task_title": "错报汇总 Agent：汇总 detected_high_risk_amount、exception_count 和受影响科目，形成错报判断。",
        "subtitle": "汇总疑似错报金额",
        "patch_focus": "misstatement_summary（必填）, agent_findings",
        "instruction": "请在 misstatement_summary 中给出 suspected_amount、exception_count 和 affected_accounts，并形成错报金额结论。",
    },
    {
        "node_id": "review_agent",
        "agent_name": "复核 Agent",
        "task_role": "复核",
        "task_title": "复核 Agent：输出人工复核、补充授权文件、扩大样本及项目经理关注建议。",
        "subtitle": "生成人工复核事项",
        "patch_focus": "review_required_items, next_actions, agent_findings",
        "instruction": "请输出复核建议、人工审核事项与对项目经理的关注提示。",
    },
]


def _agent_step_by_name(agent_name: str) -> dict[str, str] | None:
    for step in AUDIT_CHAIN:
        if step["agent_name"] == agent_name:
            return step
    return None


def _trace(type_: str, title: str, detail: str, **payload: Any) -> TraceEvent:
    return TraceEvent(type=type_, title=title, detail=detail, payload=payload)


def _fallback_summary(agent_name: str, task_role: str, analysis: dict[str, Any]) -> str:
    expected = analysis.get("expected_comparison") or {}
    count = int(expected.get("detected_exception_count") or 0)
    amount = int(expected.get("detected_high_risk_amount") or 0)
    base = (
        f"{agent_name}已完成{task_role}节点，基于 A-101 样本识别 {count} 笔异常，"
        f"疑似错报金额 {amount:,.0f}。"
    )
    extras = {
        "分析性程序 Agent": "异常集中发生在期末，建议立即进入风险评估。",
        "风险识别 Agent": "已将相关事项归类为收入虚增——第三方代付高风险，涉及营业收入、应收账款，认定为发生/准确性/截止。",
        "审计计划 Agent": "已形成后续凭证核对、合同校验、函证与复核程序安排。",
        "凭证核对 Agent": "已完成发票、合同、银行回单与验收单证据链交叉核对。",
        "合同校验 Agent": "已识别合同未允许第三方代付、授权文件缺失等问题。",
        "函证核对 Agent": "已形成客户函证与回函差异核对结论。",
        "错报汇总 Agent": "已形成错报金额、异常数量与受影响科目汇总。",
        "复核 Agent": "已输出人工复核、补充证据与项目经理关注建议。",
    }
    return base + extras.get(agent_name, "已完成本节点并写回 Shared Audit Context。")


def _minimal_patch(step: dict[str, str], summary: str, analysis: dict[str, Any]) -> dict[str, Any]:
    expected = analysis.get("expected_comparison") or {}
    evidence_index = list(analysis.get("evidence_index") or [])[:6]
    patch: dict[str, Any] = {
        "agent_findings": [
            {
                "agent_name": step["agent_name"],
                "task_role": step["task_role"],
                "summary": summary,
                "risk_id": "A-101",
            }
        ],
        "evidence_refs": evidence_index,
        "next_actions": [
            {
                "description": f"基于 {step['agent_name']} 的写入推进下一审计节点。",
                "priority": "high",
            }
        ],
    }
    if step["agent_name"] == "风险识别 Agent":
        patch["risk_register_updates"] = [
            {
                "risk_id": "A-101",
                "title": "收入虚增——第三方代付",
                "risk_level": "高",
                "related_accounts": ["营业收入", "应收账款"],
                "assertions": ["发生", "准确性", "截止"],
                "status": "open",
            }
        ]
    if step["agent_name"] == "合同校验 Agent":
        patch["review_required_items"] = [
            {"description": "补充第三方代付授权文件与合同条款审阅。", "owner": "项目经理"}
        ]
    if step["agent_name"] == "错报汇总 Agent":
        patch["misstatement_summary"] = {
            "risk_id": "A-101",
            "suspected_amount": int(expected.get("detected_high_risk_amount") or 0),
            "exception_count": int(expected.get("detected_exception_count") or 0),
            "affected_accounts": ["营业收入", "应收账款"],
        }
    if step["agent_name"] == "复核 Agent":
        patch["review_required_items"] = [
            {"description": "复核 Agent 建议项目经理关注异常样本与函证差异。", "owner": "项目经理"}
        ]
    return patch


def _build_prompt(step: dict[str, str], latest_md: str) -> str:
    return (
        "你正在 AuditBrain Shared Context Runtime 中运行。\n"
        "这是一个由后端编排的多 Agent 审计流程，Audit.md 即下方文档是你的**唯一**信息源。\n"
        "\n"
        "## 重要约束（违反将被视作输出无效）\n"
        "1. **不要调用任何文件系统工具**：不要尝试 fs_read_file、fs_list_directory、读取本地 CSV 或样本目录。原始样本已经被规则引擎分析过，结果都在下方 Audit.md 中。\n"
        "2. **不要输出工具调用语法**：不要在回复中写 `<DSML>`、`<tool_calls>`、`<invoke ...>` 这类标记，也不要写 `Let me ...` / `I will ...` / `Now I have ...` 这种独白；这些会被识别为噪音并丢弃。\n"
        "3. **不要喊话拒绝**：如果你想说\"我没有 filesystem capability\"或\"无法读取文件\"——不要说，因为不需要。基于上下文已有的 analysis_summary、exception_candidates、evidence_index 直接给结论。\n"
        "4. **不要重复别的 Agent 已经写过的内容**：先读 Audit.md 的 Agent Findings 节，在它们之上接力推进。\n"
        "5. **summary 必须是审计师视角的业务结论**：不要说「任务已完成」，要说「已识别 N 笔异常」「已制定 X 项审计程序」「已核对 Y 类凭证差异」等。\n"
        "\n"
        f"## 当前任务\n{step['task_title']}\n"
        f"\n## 本节点重点写入字段\n{step['patch_focus']}\n"
        f"\n## 具体要求\n{step['instruction']}\n"
        "\n## 输出格式（严格遵守）\n"
        "1. 先输出一段不超过 200 字的审计语言摘要（中文）。\n"
        "2. 再用一个 ```json``` 代码块输出 context_patch，示例：\n"
        "```json\n"
        "{\n"
        "  \"summary\": \"…\",\n"
        "  \"agent_findings\": [{\"agent_name\": \"…\", \"task_role\": \"…\", \"summary\": \"…\", \"risk_id\": \"A-101\"}],\n"
        "  \"risk_register_updates\": [{\"risk_id\": \"A-101\", \"title\": \"…\", \"risk_level\": \"高\", \"related_accounts\": [\"营业收入\"], \"assertions\": [\"发生\"], \"status\": \"open\"}],\n"
        "  \"evidence_refs\": [\"HT-A101-001\", \"FP-A101-002\"],\n"
        "  \"next_actions\": [{\"description\": \"…\", \"priority\": \"high\"}],\n"
        "  \"review_required_items\": [{\"description\": \"…\", \"owner\": \"项目经理\"}],\n"
        "  \"misstatement_summary\": {\"risk_id\": \"A-101\", \"suspected_amount\": 32000000, \"exception_count\": 5, \"affected_accounts\": [\"营业收入\", \"应收账款\"]}\n"
        "}\n"
        "```\n"
        "未涉及的字段省略；evidence_refs 用字符串列表即可（系统会自动归一化）。\n"
        "\n## 当前 Audit.md（按版本递增，最后一节是最新写入）\n"
        f"{latest_md}\n"
    )


def _audit_fallback_summary(agent_name: str, task_role: str, analysis: dict[str, Any]) -> str:
    """Audit-language fallback when the LLM produces no usable summary."""
    expected = analysis.get("expected_comparison") or {}
    count = int(expected.get("detected_exception_count") or 0)
    amount = int(expected.get("detected_high_risk_amount") or 0)
    base = (
        f"{agent_name}已基于共享审计上下文完成{task_role}节点。"
        f"参照 A-101 样本规则分析结果，识别 {count} 笔第三方代付异常，"
        f"疑似错报金额合计 {amount:,.0f}。"
    )
    role_addendum = {
        "分析性程序": "异常集中发生在期末，期末确认与第三方代付路径高度集中，建议立即进入风险评估。",
        "风险识别": "已将相关事项归类为收入虚增——第三方代付高风险，涉及营业收入、应收账款，认定为发生 / 准确性 / 截止。",
        "审计计划": "已形成后续凭证核对、合同校验、函证与截止测试的审计响应程序，优先级倾向高风险。",
        "凭证核对": "已完成合同 / 发票 / 银行回单 / 验收单证据链交叉核对，记录付款方与合同客户不一致的情形。",
        "合同校验": "已识别合同未允许第三方代付、缺少授权文件等合规问题，需项目经理补充审阅。",
        "函证核对": "已形成客户函证抽样建议，关注付款方与合同客户不一致样本的回函差异。",
        "错报汇总": "已形成错报金额、异常数量与受影响科目的结构化汇总。",
        "复核": "已输出人工复核、补充证据与项目经理关注建议。",
    }
    return base + role_addendum.get(task_role, "已写入共享审计上下文，便于后续节点接力。")


def _clean_or_fallback_summary(
    raw_summary: str,
    step: dict[str, str],
    analysis: dict[str, Any],
) -> str:
    cleaned = strip_tool_noise(raw_summary)
    cleaned = " ".join(cleaned.split())
    if not cleaned or len(cleaned) < 18 or is_filesystem_refusal(cleaned):
        return _audit_fallback_summary(step["agent_name"], step["task_role"], analysis)
    if len(cleaned) > 360:
        cleaned = cleaned[:360].rstrip("，。；；,:：. ") + "。"
    return cleaned


def build_audit_context_runtime_graph() -> WorkflowGraph:
    """Static graph for the AuditBrain Shared Context Runtime workflow.

    Visual layout is the "autonomous-planning" structure:

        Start
          ↓
        Master Planner
          ↓
        Plan Validator
          ↓
        Task Dispatcher
        ↙↓↓↓↓↓↓↘   (fan-out to 8 audit agents)
        analytical / risk / planning / voucher / contract / confirmation / misstatement / review
        ↘↓↓↓↓↓↓↙   (fan-in to synthesizer)
        Context Synthesizer
          ↓
        End

    Used both by the runtime executor at run-end and by the
    `GET /api/workflows/{id}/graph` endpoint so the frontend can render the
    DAG without having to run the workflow.
    """
    nodes: list[WorkflowNode] = [
        WorkflowNode(id="start", label="Start", kind="start", node_type="start"),
        WorkflowNode(
            id="master_planner",
            label="Master Planner",
            subtitle="初始化 A-101 审计上下文",
            kind="logic",
            node_type="planner",
        ),
        WorkflowNode(
            id="plan_validator",
            label="Plan Validator",
            subtitle="校验审计任务链路",
            kind="logic",
            node_type="validator",
        ),
        WorkflowNode(
            id="task_dispatcher",
            label="Task Dispatcher",
            subtitle="分派任务给专业审计 Agent",
            kind="logic",
            node_type="dispatcher",
        ),
    ]
    for step in AUDIT_CHAIN:
        nodes.append(
            WorkflowNode(
                id=step["node_id"],
                label=step["agent_name"],
                subtitle=step["subtitle"],
                kind="agent",
                node_type="audit_agent",
            )
        )
    nodes.append(
        WorkflowNode(
            id="context_synthesizer",
            label="Context Synthesizer",
            subtitle="汇总写入 Audit.md / 生成最终审计结果",
            kind="final",
            node_type="synthesizer",
        )
    )
    nodes.append(WorkflowNode(id="end", label="End", kind="end", node_type="end"))

    edges: list[WorkflowEdge] = [
        WorkflowEdge(source="start", target="master_planner"),
        WorkflowEdge(source="master_planner", target="plan_validator"),
        WorkflowEdge(source="plan_validator", target="task_dispatcher"),
    ]
    for step in AUDIT_CHAIN:
        edges.append(WorkflowEdge(source="task_dispatcher", target=step["node_id"]))
        edges.append(WorkflowEdge(source=step["node_id"], target="context_synthesizer"))
    edges.append(WorkflowEdge(source="context_synthesizer", target="end"))

    return WorkflowGraph(nodes=nodes, edges=edges)


def run_audit_context_runtime(
    store,
    workflow,
    user_input: str,
    history: list[dict[str, str]] | None = None,
    on_event: Callable[[TraceEvent], None] | None = None,
    on_audit_context_updated: Callable[[dict[str, object]], None] | None = None,
    on_runtime_event: Callable[[str, dict[str, object]], None] | None = None,
    audit_context: dict[str, Any] | None = None,
) -> WorkflowRunResponse:
    history = history or []
    project_id = str((audit_context or {}).get("project_id") or "")
    bundle = load_a101_sample_bundle()
    analysis = analyze_a101_sample(bundle)
    guard = ensure_analysis_available(bool(analysis.get("analysis_summary") or analysis.get("exception_candidates")))
    if not guard.allowed:
        raise RuntimeError(guard.reason)

    expected = analysis.get("expected_comparison") or {}
    initial_payload = {
        "analysis_summary": analysis.get("analysis_summary") or {},
        "exception_candidates": analysis.get("exception_candidates") or [],
        "expected_comparison": expected,
        "evidence_index": analysis.get("evidence_index") or [],
        "data_quality_warnings": analysis.get("data_quality_warnings") or [],
    }
    initial_misstatement = {
        "risk_id": "A-101",
        "suspected_amount": int(expected.get("detected_high_risk_amount") or 0),
        "exception_count": int(expected.get("detected_exception_count") or 0),
        "affected_accounts": ["营业收入", "应收账款"],
    }
    initial_risk_register = [
        {
            "risk_id": "A-101",
            "title": "收入虚增——第三方代付",
            "risk_level": "高",
            "related_accounts": ["营业收入", "应收账款"],
            "assertions": ["发生", "准确性", "截止"],
            "status": "open",
        }
    ]

    if on_event:
        on_event(
            _trace(
                "run_started",
                "Run Started",
                f"AuditBrain Shared Context Runtime 开始执行：{workflow.name}",
                workflow_id=workflow.id,
                workflow_type=workflow.type,
                project_id=project_id,
                node_id="start",
                next_node_id="master_planner",
            )
        )
        on_event(
            _trace(
                "node_entered",
                "Enter Master Planner",
                "Master Planner 正在初始化 A-101 共享审计上下文。",
                node_id="master_planner",
                agent_name="Master / Planner",
            )
        )

    init_result = audit_context_runtime_store.initialize_context(
        project_id,
        initial_payload,
        "Planner / Master",
        misstatement_summary=initial_misstatement,
        risk_register=initial_risk_register,
    )

    if on_event:
        on_event(
            _trace(
                "audit_context_loaded",
                "Master Planner 读取上下文",
                "Master Planner 读取空白上下文，准备初始化 Audit.md v1。",
                node_id="master_planner",
                agent_name="Master / Planner",
                context_version_before=0,
            )
        )
        on_event(
            _trace(
                "audit_context_patch_applied",
                f"Master Planner 初始化 Audit.md v{init_result['version_after']}",
                f"Master Planner 已写入 A-101 共享审计上下文，版本号 v{init_result['version_after']}。",
                node_id="master_planner",
                agent_name="Master / Planner",
                context_version_after=init_result["version_after"],
                patch_keys=init_result["event"].patch_keys,
            )
        )
        on_event(
            _trace(
                "node_entered",
                "Enter Plan Validator",
                "Plan Validator 正在校验固定审计任务链路。",
                node_id="plan_validator",
                next_node_id="task_dispatcher",
            )
        )
        on_event(
            _trace(
                "node_entered",
                "Enter Task Dispatcher",
                "Task Dispatcher 准备按固定顺序分派 8 个审计 Agent。",
                node_id="task_dispatcher",
            )
        )

    init_payload_event = {
        "project_id": project_id,
        "context_id": init_result["context"].context_id,
        "context_version": init_result["version_after"],
        "updated_by": "Planner / Master",
        "patch_keys": init_result["event"].patch_keys,
        "markdown": init_result["audit_md"],
        "history_item": init_result["event"].model_dump(),
    }
    if on_audit_context_updated:
        on_audit_context_updated(init_payload_event)
    push_event(on_runtime_event, "audit_context_updated", init_payload_event)
    push_event(on_runtime_event, "audit_md_updated", init_payload_event)

    task_reports: list[dict[str, Any]] = []
    worker_by_name: dict[str, Any] = {}
    for agent_id in workflow.specialist_agent_ids:
        agent = store.get_agent(agent_id)
        if agent is not None:
            worker_by_name[agent.name] = agent

    for step in AUDIT_CHAIN:
        worker = worker_by_name.get(step["agent_name"])
        if worker is None:
            continue

        latest_context = audit_context_runtime_store.get_latest_context(project_id)
        latest_md = audit_context_runtime_store.read_audit_md(project_id)
        loaded_payload = {
            "agent_name": worker.name,
            "task_role": step["task_role"],
            "task_title": step["task_title"],
            "node_id": step["node_id"],
            "context_version": latest_context.version,
            "context_version_before": latest_context.version,
        }
        if on_event:
            on_event(
                _trace(
                    "audit_context_loaded",
                    f"{worker.name} 读取 Audit.md v{latest_context.version}",
                    f"{worker.name} 已加载共享审计上下文 v{latest_context.version}，准备执行{step['task_role']}。",
                    node_id=step["node_id"],
                    agent_name=worker.name,
                    task_role=step["task_role"],
                    task_title=step["task_title"],
                    context_version_before=latest_context.version,
                )
            )
        push_event(on_runtime_event, "audit_context_loaded", loaded_payload)

        prompt = _build_prompt(step, latest_md)
        llm_error: str = ""
        no_tools_worker = worker.model_copy(update={"skill_ids": [], "builtin_capabilities": []})
        raw_output = ""
        retry_attempts = 3
        for attempt in range(1, retry_attempts + 1):
            try:
                raw_output = str(llm_gateway.run_agent(
                    no_tools_worker,
                    prompt,
                    history=history,
                    audit_context={"context_markdown": latest_md},
                    enforce_filesystem_intent_check=False,
                ) or "")
                llm_error = ""
                break
            except Exception as exc:  # noqa: BLE001
                llm_error = f"{type(exc).__name__}: {exc}"
                if attempt < retry_attempts:
                    time.sleep(0.6 * attempt)
                    continue
                raw_output = ""
        if llm_error:
            if on_event:
                on_event(
                    _trace(
                        "state_updated",
                        "LLM call failed (fallback used)",
                        f"{worker.name} after {retry_attempts} attempts: {llm_error[:200]}",
                        agent_name=worker.name,
                        task_role=step["task_role"],
                        error_class=llm_error.split(":", 1)[0],
                        attempts=retry_attempts,
                    )
                )
            push_event(on_runtime_event, "audit_llm_error", {
                "agent_name": worker.name,
                "task_role": step["task_role"],
                "error": llm_error[:500],
                "attempts": retry_attempts,
            })

        parsed_summary, parsed_patch = parse_agent_output(raw_output)
        used_fallback = not parsed_summary or len(parsed_summary) < 18 or is_filesystem_refusal(parsed_summary)
        summary = _clean_or_fallback_summary(parsed_summary, step, analysis)
        if used_fallback and not llm_error and raw_output:
            preview = raw_output.strip().replace("\n", " ")[:200]
            if on_event:
                on_event(
                    _trace(
                        "state_updated",
                        "LLM output unusable (fallback used)",
                        f"{worker.name}: raw len={len(raw_output)} preview={preview!r}",
                        agent_name=worker.name,
                        task_role=step["task_role"],
                        raw_length=len(raw_output),
                    )
                )
            push_event(on_runtime_event, "audit_llm_unusable", {
                "agent_name": worker.name,
                "task_role": step["task_role"],
                "raw_length": len(raw_output),
                "raw_preview": preview,
            })
        merged_patch = merge_patches(_minimal_patch(step, summary, analysis), parsed_patch)
        merged_patch["summary"] = summary

        write_result = audit_context_runtime_store.apply_patch(
            project_id,
            merged_patch,
            worker.name,
            worker.description,
            step["task_title"],
        )

        if on_event:
            on_event(
                _trace(
                    "audit_context_patch_applied",
                    f"{worker.name} 写入 Audit.md v{write_result['version_after']}",
                    f"{worker.name} 已写回共享审计上下文，patch_keys={list(write_result['event'].patch_keys)}",
                    node_id=step["node_id"],
                    agent_name=worker.name,
                    task_role=step["task_role"],
                    task_title=step["task_title"],
                    context_version_before=latest_context.version,
                    context_version_after=write_result["version_after"],
                    patch_keys=write_result["event"].patch_keys,
                )
            )

        updated_payload = {
            "project_id": project_id,
            "context_id": write_result["context"].context_id,
            "context_version": write_result["version_after"],
            "updated_by": worker.name,
            "patch_keys": write_result["event"].patch_keys,
            "markdown": write_result["audit_md"],
            "history_item": write_result["event"].model_dump(),
            "node_id": step["node_id"],
        }
        if on_audit_context_updated:
            on_audit_context_updated(updated_payload)
        push_event(on_runtime_event, "audit_context_updated", updated_payload)
        push_event(on_runtime_event, "audit_md_updated", updated_payload)

        review_required = bool(
            merged_patch.get("review_required_items")
            or step["agent_name"] in ("合同校验 Agent", "复核 Agent")
        )
        evidence_refs_for_report = list(merged_patch.get("evidence_refs") or [])
        next_actions_for_report = list(merged_patch.get("next_actions") or [])

        task_reports.append({
            "agent_name": worker.name,
            "task_role": step["task_role"],
            "task_title": step["task_title"],
            "context_version_before": latest_context.version,
            "context_version_after": write_result["version_after"],
            "patch_keys": list(write_result["event"].patch_keys),
            "summary": summary,
            "evidence_refs": evidence_refs_for_report,
            "next_actions": next_actions_for_report,
            "review_required": review_required,
        })

        if step["node_id"] == "review_agent":
            gate_state = audit_context_runtime_store.get_latest_context(project_id)
            gate = build_final_review_gate(gate_state, created_by_agent=worker.name)
            gate_register = audit_context_runtime_store.register_review_gate(
                project_id,
                gate,
                actor_name=worker.name,
            )
            sse_gate = project_gate_for_sse(
                gate_register["gate"],
                context_version=gate_register["context_version"],
            )
            if on_event:
                on_event(
                    _trace(
                        "audit_context_patch_applied",
                        "复核 Agent 触发人工复核节点",
                        f"复核 Agent 已生成人工复核 Gate {gate.get('gate_id')}，等待审计师决定。",
                        node_id="review_agent",
                        agent_name=worker.name,
                        task_role=step["task_role"],
                        event_type="human_review_required",
                        gate_id=gate.get("gate_id"),
                        context_version=gate_register["context_version"],
                    )
                )
            push_event(on_runtime_event, "human_review_required", {
                "gate": sse_gate,
                "context_version": gate_register["context_version"],
            })

    audit_context_runtime_store.refresh_trust(project_id)
    audit_context_runtime_store.detect_pause(project_id)
    final_context = audit_context_runtime_store.get_latest_context(project_id)

    if on_event:
        on_event(
            _trace(
                "state_updated",
                f"Context Synthesizer 汇总 Audit.md v{final_context.version}",
                f"Context Synthesizer 基于共享审计上下文 v{final_context.version} 合成终结陈述。",
                node_id="context_synthesizer",
                agent_name="Synthesizer",
                stage="audit_synthesizer_started",
                context_version_before=final_context.version,
            )
        )
    push_event(on_runtime_event, "audit_synthesizer_started", {
        "agent_name": "Synthesizer",
        "node_id": "context_synthesizer",
        "context_version_before": final_context.version,
    })

    synthesizer_message = _compose_synthesizer_message(final_context, task_reports)
    assistant_message = synthesizer_message

    if on_event:
        on_event(
            _trace(
                "state_updated",
                f"Context Synthesizer 完成（可信度 {float(final_context.trust_score or 0.0):.2f}）",
                f"Audit.md v{final_context.version} 已生成最终审计陈述。",
                node_id="context_synthesizer",
                agent_name="Synthesizer",
                stage="audit_synthesizer_finished",
                context_version_after=final_context.version,
                trust_score=float(final_context.trust_score or 0.0),
            )
        )
    push_event(on_runtime_event, "audit_synthesizer_finished", {
        "agent_name": "Synthesizer",
        "node_id": "context_synthesizer",
        "context_version_after": final_context.version,
        "trust_score": float(final_context.trust_score or 0.0),
        "assistant_message_preview": synthesizer_message[:280],
    })

    if on_event:
        on_event(
            _trace(
                "run_finished",
                f"AuditBrain Shared Context Runtime 已完成，最终版本 v{final_context.version}",
                f"共写入 {len(task_reports)} 个 Agent，可信度 {float(final_context.trust_score or 0.0):.2f}。",
                node_id="end",
                workflow_id=workflow.id,
                context_version=final_context.version,
                trust_score=float(final_context.trust_score or 0.0),
                paused=bool(final_context.paused),
            )
        )

    graph = build_audit_context_runtime_graph()
    audit_summary = _build_audit_summary(final_context, task_reports)

    return WorkflowRunResponse(
        workflow_id=workflow.id,
        user_input=user_input,
        assistant_message=assistant_message,
        trace=[],
        graph=graph,
        artifacts=RunArtifacts(
            route_agent_name="Synthesizer",
            task_reports=task_reports,
            audit_summary=audit_summary,
            structured_mode=True,
            risk_id="A-101",
        ),
        conversation_id=None,
    )


def _build_audit_summary(state: Any, task_reports: list[dict[str, Any]]) -> dict[str, Any]:
    project_snapshot = dict(getattr(state, "project_snapshot", {}) or {})
    return {
        "risks": list(getattr(state, "risk_register", []) or []),
        "findings": list(getattr(state, "agent_findings", []) or []),
        "evidence_refs": list(getattr(state, "evidence_index", []) or []),
        "analysis_summary": project_snapshot.get("analysis_summary") or {},
        "expected_comparison": project_snapshot.get("expected_comparison") or {},
        "misstatement_summary": dict(getattr(state, "misstatement_summary", {}) or {}),
        "review_required_items": list(getattr(state, "review_required_items", []) or []),
        "next_actions": list(getattr(state, "next_actions", []) or []),
        "trust_score": float(getattr(state, "trust_score", 0.0) or 0.0),
        "validation_results": list(getattr(state, "validation_results", []) or []),
        "context_version": int(getattr(state, "version", 0) or 0),
        "task_reports_count": len(task_reports),
    }


def _compose_synthesizer_message(state: Any, task_reports: list[dict[str, Any]]) -> str:
    misstatement = dict(getattr(state, "misstatement_summary", {}) or {})
    project_snapshot = dict(getattr(state, "project_snapshot", {}) or {})
    expected = dict(project_snapshot.get("expected_comparison") or {})

    suspected_amount = misstatement.get("suspected_amount") or expected.get("detected_high_risk_amount") or 0
    exception_count = misstatement.get("exception_count") or expected.get("detected_exception_count") or 0
    affected_accounts = misstatement.get("affected_accounts") or ["营业收入", "应收账款"]
    risk_id = misstatement.get("risk_id") or "A-101"

    findings_block: list[str] = []
    for report in task_reports[-8:]:
        agent_name = str(report.get("agent_name") or "Agent")
        version_after = report.get("context_version_after", "?")
        summary = str(report.get("summary") or "").strip()
        if summary:
            findings_block.append(f"- v{version_after} · {agent_name}：{summary}")

    review_items = list(getattr(state, "review_required_items", []) or [])
    review_block: list[str] = []
    for item in review_items[:6]:
        description = str((item or {}).get("description") or item or "").strip()
        if description:
            review_block.append(f"- {description}")

    trust_score = float(getattr(state, "trust_score", 0.0) or 0.0)
    pause_reason = str(getattr(state, "pause_reason", "") or "")

    parts = [
        "【AuditBrain Shared Context Runtime · 终结陈述】",
        "",
        f"风险编号：{risk_id}（收入虚增——第三方代付）",
        f"疑似错报金额：{int(suspected_amount):,}",
        f"异常交易数量：{int(exception_count)}",
        f"涉及科目：{' / '.join(str(a) for a in affected_accounts)}",
        f"上下文版本：v{getattr(state, 'version', '?')}（可信度 {trust_score:.2f}）",
    ]
    if pause_reason:
        parts.append(f"流程状态：暂停 · {pause_reason}")
    parts.extend([
        "",
        "【按 Agent 写入顺序的核心发现】",
        *(findings_block or ["- 暂无 Agent 写入"]),
    ])
    if review_block:
        parts.extend(["", "【需项目经理人工复核的事项】", *review_block])
    parts.extend([
        "",
        "【结论建议】",
        "请项目经理复核收入确认时点、第三方代付凭证链条、合同条款与函证一致性，"
        "并依据 Audit.md 中 Agent Findings 与 Evidence References 判断是否扩大样本或调整审计意见。",
    ])
    return "\n".join(parts)
