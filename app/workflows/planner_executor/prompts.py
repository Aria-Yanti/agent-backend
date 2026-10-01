# Planner Executor workflow prompts

from ...schemas import AgentDefinition


AUDIT_DEMO_SCENARIO = {
    "risk_code": "A-101",
    "risk_name": "收入虚增——第三方代付",
    "suspected_misstatement_amount": 32000000,
    "related_accounts": ["营业收入", "应收账款"],
    "assertions": ["发生", "准确性", "截止"],
}


REAL_ANALYSIS_INSTRUCTION = (
    "If the Shared Audit Context contains an 'A-101 Sample Data Analysis' section, you must prioritize those real analysis results over the default demo scenario. "
    "Do not generalize when specific revenue_id, contract_no, invoice_no, payer_name, amount, exception_type, risk_level, evidence_refs, expected_comparison, or data_quality_warnings are available. "
    "Never paste full tables back; cite only the relevant abnormal items and their evidence chain."
)


STRUCTURED_OUTPUT_REQUIREMENTS = (
    "Return a JSON object only. Do not output markdown. Use this exact shape: "
    '{"summary":"...","context_patch":{"project_snapshot":{},"agent_findings":[],"next_actions":[],"evidence_refs":[]},'
    '"evidence_refs":[],"risk_updates":[],"next_actions":[],"review_required":false,"confidence":"medium"}. '
    "Each agent should include real evidence_refs whenever possible, using concrete references such as HT-2025-0036, FP-2025-0036, BS-2025-0036. "
    "Each agent should include at least one actionable next_actions item when abnormalities exist. "
    "Use risk_updates to describe A-101 risk status changes, and set review_required=true when manual review, missing authorization, sample expansion, or manager attention is needed. "
    "For backward compatibility only, CONTEXT_PATCH_JSON is allowed, but full JSON object is strongly preferred."
)



def _build_structured_output_contract() -> str:
    return STRUCTURED_OUTPUT_REQUIREMENTS



def _build_common_a101_guidance(agent_specific: str) -> str:
    return (
        f"{REAL_ANALYSIS_INSTRUCTION}\n"
        f"{agent_specific}\n"
        "When real exception candidates exist, explicitly mention relevant revenue_id values and preserve evidence_refs in both top-level evidence_refs and context_patch.evidence_refs."
    )



def build_analytical_procedure_agent_prompt(context_markdown: str, task: str) -> str:
    guidance = _build_common_a101_guidance(
        "You must cite detected_exception_count, detected_high_risk_amount, period-end receipt/revenue concentration, and the abnormal third-party payment population."
    )
    return (
        "You are the Analytical Procedure Agent for an audit workflow.\n"
        "Analyze the audit context, identify anomalies, unusual trends, and preliminary hypotheses.\n"
        f"{guidance}\n"
        f"Shared Audit Context:\n{context_markdown}\n\n"
        f"Current Task:\n{task}\n\n"
        f"Default Demo Scenario: {AUDIT_DEMO_SCENARIO}\n"
        f"{_build_structured_output_contract()}"
    )



def build_risk_identification_agent_prompt(context_markdown: str, task: str) -> str:
    guidance = _build_common_a101_guidance(
        "You must identify A-101 risk directly from exception_candidates instead of describing generic revenue fraud risk."
    )
    return (
        "You are the Risk Identification Agent for an audit workflow.\n"
        "Identify audit risks, affected assertions, and prioritize which risks require follow-up.\n"
        f"{guidance}\n"
        f"Shared Audit Context:\n{context_markdown}\n\n"
        f"Current Task:\n{task}\n\n"
        f"Default Demo Scenario: {AUDIT_DEMO_SCENARIO}\n"
        f"{_build_structured_output_contract()}"
    )



def build_audit_planning_agent_prompt(context_markdown: str, task: str) -> str:
    guidance = _build_common_a101_guidance(
        "You must generate procedures from the real abnormal patterns, including HT/FP/BS evidence chain inspection, third-party authorization retrieval, confirmations for abnormal customers, and cutoff checks between acceptance date and revenue recognition date."
    )
    return (
        "You are the Audit Planning Agent.\n"
        "Turn the identified risks into executable audit procedures, scope, and sequencing.\n"
        f"{guidance}\n"
        f"Shared Audit Context:\n{context_markdown}\n\n"
        f"Current Task:\n{task}\n\n"
        f"Default Demo Scenario: {AUDIT_DEMO_SCENARIO}\n"
        f"{_build_structured_output_contract()}"
    )



def build_voucher_checking_agent_prompt(context_markdown: str, task: str) -> str:
    guidance = _build_common_a101_guidance(
        "You must reference concrete revenue_id, contract_no, invoice_no, bank slip id, and evidence_refs when discussing support for exceptions."
    )
    return (
        "You are the Voucher Checking Agent.\n"
        "Focus on verifying voucher-level evidence and accounting support for the target risk.\n"
        f"{guidance}\n"
        f"Shared Audit Context:\n{context_markdown}\n\n"
        f"Current Task:\n{task}\n\n"
        f"Default Demo Scenario: {AUDIT_DEMO_SCENARIO}\n"
        f"{_build_structured_output_contract()}"
    )



def build_contract_review_agent_prompt(context_markdown: str, task: str) -> str:
    guidance = _build_common_a101_guidance(
        "You must focus on whether third_party_allowed is 否, whether authorization_file_no is empty, and whether the contractual payer differs from the actual payer."
    )
    return (
        "You are the Contract Review Agent.\n"
        "Review contracts or supporting commercial terms relevant to the risk and assertions.\n"
        f"{guidance}\n"
        f"Shared Audit Context:\n{context_markdown}\n\n"
        f"Current Task:\n{task}\n\n"
        f"Default Demo Scenario: {AUDIT_DEMO_SCENARIO}\n"
        f"{_build_structured_output_contract()}"
    )



def build_confirmation_checking_agent_prompt(context_markdown: str, task: str) -> str:
    guidance = _build_common_a101_guidance(
        "You must produce confirmation suggestions tied to exception_candidates and the affected customers."
    )
    return (
        "You are the Confirmation Checking Agent.\n"
        "Review confirmation-related evidence and third-party corroboration for the target risk.\n"
        f"{guidance}\n"
        f"Shared Audit Context:\n{context_markdown}\n\n"
        f"Current Task:\n{task}\n\n"
        f"Default Demo Scenario: {AUDIT_DEMO_SCENARIO}\n"
        f"{_build_structured_output_contract()}"
    )



def build_misstatement_summary_agent_prompt(context_markdown: str, task: str) -> str:
    guidance = _build_common_a101_guidance(
        "You must summarize detected_high_risk_amount = 32000000, exception_count = 5, and affected_accounts = 营业收入、应收账款 when those real values exist in context."
    )
    return (
        "You are the Misstatement Summary Agent.\n"
        "Aggregate suspected misstatements, quantify them where possible, and summarize unresolved issues.\n"
        f"{guidance}\n"
        f"Shared Audit Context:\n{context_markdown}\n\n"
        f"Current Task:\n{task}\n\n"
        f"Default Demo Scenario: {AUDIT_DEMO_SCENARIO}\n"
        f"{_build_structured_output_contract()}"
    )



def build_review_agent_prompt(context_markdown: str, task: str) -> str:
    guidance = _build_common_a101_guidance(
        "You must conclude whether manual review is required, whether authorization files are missing, whether sample expansion is recommended, and whether project manager attention is needed."
    )
    return (
        "You are the Review Agent.\n"
        "Assess whether the prior audit work is coherent, whether additional procedures are needed, and provide review recommendations.\n"
        f"{guidance}\n"
        f"Shared Audit Context:\n{context_markdown}\n\n"
        f"Current Task:\n{task}\n\n"
        f"Default Demo Scenario: {AUDIT_DEMO_SCENARIO}\n"
        f"{_build_structured_output_contract()}"
    )


AUDIT_TEMPLATE_TASKS = [
    "分析性程序 Agent：引用真实 A-101 分析结果，围绕期末集中确认、第三方代付异常数量与金额执行分析性程序。",
    "风险识别 Agent：基于 exception_candidates 识别 A-101 风险、影响认定及优先级。",
    "审计计划 Agent：基于真实异常类型制定审计程序，包括 HT/FP/BS 证据链、授权文件、函证与截止测试。",
    "凭证核对 / 合同校验 / 函证核对：引用 revenue_id、contract_no、invoice_no、bank slip id 与 evidence_refs 核对支持证据。",
    "错报汇总 Agent：汇总 detected_high_risk_amount、exception_count 和受影响科目，形成错报判断。",
    "复核 Agent：输出人工复核、补充授权文件、扩大样本及项目经理关注建议。",
]


def build_audit_template_tasks() -> list[str]:
    return list(AUDIT_TEMPLATE_TASKS)


# Planner prompt - decomposes user request into tasks
PLAN_TASKS_PROMPT = """You are a planning module.
Decompose the user request into at most {max_tasks} executable tasks.
{multi_hint}
{agent_catalog}
Return ONLY a JSON array of strings.
User request: {user_input}"""


def build_plan_tasks_prompt(
    user_input: str,
    max_tasks: int = 4,
    force_multi: bool = False,
    agents: list[AgentDefinition] | None = None,
) -> str:
    """Build the planner prompt."""
    multi_hint = (
        "Prefer at least 2 tasks when the request includes multiple intents."
        if force_multi
        else "Use the minimum number of tasks needed."
    )

    agent_catalog = ""
    if agents:
        catalog_lines = "\n".join(
            f"- name={agent.name}; description={agent.description}"
            for agent in agents
        )
        agent_catalog = (
            "Available specialists:\n"
            f"{catalog_lines}\n"
            "Plan tasks so they map clearly onto the available specialists.\n"
            "When the request reasonably spans product/design/engineering, reflect that in the task split.\n"
            "Prefer task wording that makes the best specialist obvious.\n"
        )

    return PLAN_TASKS_PROMPT.format(
        user_input=user_input,
        max_tasks=max_tasks,
        multi_hint=multi_hint,
        agent_catalog=agent_catalog,
    )


# Keywords that indicate multi-task requests
MULTI_HINT_KEYWORDS = (
    " and ",
    " also ",
    " then ",
    "同时",
    "另外",
    "并且",
    "然后",
    "接着",
    "最后",
)


def should_force_multi(user_input: str) -> bool:
    """Check if the user input suggests multiple tasks."""
    return any(kw in user_input for kw in MULTI_HINT_KEYWORDS)


# Fallback planner - simple task splitting by punctuation
def fallback_plan_tasks(user_input: str, max_tasks: int = 4) -> list[str]:
    """Fallback task planning by simple splitting."""
    separators = ["，", "。", ";", "\n"]
    tasks = [user_input]

    for sep in separators:
        new_tasks = []
        for task in tasks:
            new_tasks.extend(task.split(sep))
        if len(new_tasks) > len(tasks):
            tasks = new_tasks
            break

    tasks = [t.strip() for t in tasks if t.strip()]
    return tasks[:max_tasks]


ROUTER_PROMPT = """你是 workflow router。请从下面的 specialist agent 中选出最适合处理用户请求的一个。
只返回一行，格式必须是：agent_id|reason
可选 agent:
{agent_catalog}
用户请求：{user_input}"""


def build_router_prompt(user_input: str, agents: list[AgentDefinition]) -> str:
    """Build the router prompt with agent catalog."""
    catalog = "\n".join(
        f"- id={agent.id}; name={agent.name}; description={agent.description}"
        for agent in agents
    )
    return ROUTER_PROMPT.format(
        user_input=user_input,
        agent_catalog=catalog,
    )


FALLBACK_ROUTE_KEYWORDS: dict[str, list[str]] = {
    "architecture": ["架构", "architecture", "design", "边界", "模块"],
    "writing": ["写", "总结", "文档", "改写", "说明"],
    "learning": ["学习", "路径", "怎么学", "建议", "步骤"],
}


def fallback_route_keyword(user_input: str, agents: list[AgentDefinition]) -> tuple[str, str] | None:
    """Fallback routing by keyword matching."""
    input_lower = user_input.lower()
    for agent_id, keywords in FALLBACK_ROUTE_KEYWORDS.items():
        if any(kw.lower() in input_lower for kw in keywords):
            for agent in agents:
                if agent.id == agent_id or agent_id in agent.name.lower():
                    return agent.id, f"keyword match: {keywords}"
    return None


FINALIZE_PROMPT = """你是 workflow finalizer。请根据用户原始请求和 specialist 的回答，
输出最终对用户可见的答案，控制在 6 句话以内。
用户请求：{user_input}
specialist: {agent_name}
specialist 回复：{specialist_answer}"""


def build_finalize_prompt(
    user_input: str,
    agent: AgentDefinition,
    specialist_answer: str,
) -> str:
    return FINALIZE_PROMPT.format(
        user_input=user_input,
        agent_name=agent.name,
        specialist_answer=specialist_answer,
    )


FALLBACK_FINALIZE_RESPONSE = (
    "系统已将请求路由给 {agent_name}。\n"
    "{agent_name} 的回答如下：\n{answer}"
)


def build_fallback_response(agent_name: str, answer: str) -> str:
    return FALLBACK_FINALIZE_RESPONSE.format(
        agent_name=agent_name,
        answer=answer,
    )


def is_audit_template_mode(context: dict[str, object] | None) -> bool:
    if not context:
        return False
    if context.get("project_id"):
        return True
    project_snapshot = context.get("project_snapshot")
    return isinstance(project_snapshot, dict) and bool(project_snapshot)
