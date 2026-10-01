# Supervisor Dynamic workflow prompts

from ...schemas import AgentDefinition


# Router prompt - same as other workflows
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


# Supervisor review prompt - decides whether to continue delegation
SUPERVISOR_REVIEW_PROMPT = """You are a supervisor loop controller.
Given the original user request and worker reports, decide whether to continue delegation.
Respond with JSON only in this shape:
{{"continue": true/false, "next_focus_task": "<string>", "reason": "<string>"}}
Rules:
- If current output is sufficient and coherent, set continue=false.
- If key requirements are missing, set continue=true and provide the next focus task.
- Current cycle: {cycle}, max cycles: {max_cycles}.

User request:
{user_input}

Recent reports:
{report_block}"""


def build_supervisor_review_prompt(
    user_input: str,
    reports: list[str],
    cycle: int,
    max_cycles: int,
) -> str:
    """Build the supervisor review prompt."""
    recent_reports = reports[-3:] if reports else []
    report_block = "\n\n".join(recent_reports) if recent_reports else "(no reports yet)"
    return SUPERVISOR_REVIEW_PROMPT.format(
        user_input=user_input,
        report_block=report_block,
        cycle=cycle,
        max_cycles=max_cycles,
    )


# Fallback keywords for supervisor
SUPERVISOR_FALLBACK_KEYWORDS_UNRESOLVED = (
    "todo",
    "unknown",
    "risk",
    "assumption",
    "待补充",
    "未知",
    "风险",
    "假设",
)

SUPERVISOR_FALLBACK_KEYWORDS_COMPLETE = (
    "final",
    "complete",
    "done",
    "conclusion",
    "最终",
    "结论",
    "已完成",
)


def fallback_supervisor_review_decision(
    user_input: str,
    reports: list[str],
    cycle: int,
    max_cycles: int,
) -> tuple[bool, str, str]:
    """Fallback supervisor decision based on keywords."""
    if cycle >= max_cycles:
        return False, "", "Reached max cycle limit."
    
    if not reports:
        return True, "Start with the first task.", "No reports yet."
    
    latest = reports[-1].lower()
    unresolved_markers = SUPERVISOR_FALLBACK_KEYWORDS_UNRESOLVED
    complete_markers = SUPERVISOR_FALLBACK_KEYWORDS_COMPLETE
    
    if any(token in latest for token in unresolved_markers):
        return True, "针对未解决项继续补充可执行细节。", "Fallback: latest report indicates unresolved items."
    if any(token in latest for token in complete_markers):
        return False, "", "Fallback: latest report appears complete."
    return False, "", "Fallback: no strong signal to continue."


# Finalizer prompt
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
