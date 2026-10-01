# Router Specialists workflow prompts

from ...schemas import AgentDefinition


# Router prompt - used to select the best specialist agent
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


# Fallback routing keywords
FALLBACK_ROUTE_KEYWORDS = {
    "architecture": ["架构", "architecture", "design", "边界", "模块"],
    "writer": ["写", "总结", "文档", "改写", "说明"],
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


# Finalizer prompt - same as single_agent_chat
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
