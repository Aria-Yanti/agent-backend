# Peer Handoff workflow prompts

from ...schemas import AgentDefinition


PEER_EXECUTION_FINAL_RESPONSE_INSTRUCTION = (
    "Using the tool results already collected above, respond with an execution summary only. "
    "Do not decide workflow actions in this step. "
    "Only claim files, directories, artifacts, validations, and implemented behavior that are explicitly supported by successful tool results in this run. "
    "If something is still missing, say it is still missing. "
    "Do not invent created files, completed functionality, or successful verification that did not happen."
)


def _build_peer_execution_prompt(
    *,
    user_input: str,
    current_task_title: str,
    peer_directory: str,
    available_outputs: str,
    workspace_context: str,
) -> str:
    return (
        "# Peer Task Execution\n"
        "Execute the current task directly. Do not output workflow action JSON in this step.\n\n"
        "## Execution rules\n"
        "- Focus on doing the current task, not deciding the next workflow action.\n"
        "- The confirmed delivery/workspace path below is authoritative shared team state. Preserve it across all file operations and handoffs.\n"
        "- When filesystem work is needed and a confirmed delivery/workspace path is present, use absolute fs_* paths rooted at that location.\n"
        "- Do not use bare relative filesystem paths for delivery work in this workflow.\n"
        "- If the current task is not fully complete and you can continue, continue executing instead of returning a progress update.\n"
        "- If the task gives a clear target path or deliverable, create or update it directly; inspect first only when the path is ambiguous, existing content must be preserved, or you need facts you do not have.\n"
        "- Prefer doing the necessary file operations over repeatedly listing or describing what should be done.\n"
        "- Make reasonable assumptions and continue when optional preferences or non-critical details are missing.\n"
        "- Do not pause execution just to ask for style, naming, or preference details that can be sensibly defaulted.\n"
        "- Only report files, directories, documents, mockups, screenshots, code, behaviors, or artifacts that you actually created or verified with successful tool results in this run.\n"
        "- If a file or artifact has not been created yet, say it is not yet created; do not imply it already exists.\n"
        "- If functionality has not been implemented or verified yet, say it is still missing; do not describe it as already working.\n"
        "- Never invent tool results, file contents, validation outcomes, browser checks, or successful delivery states.\n"
        "- If you cannot complete the current task, state the real blocker and what you already completed or verified.\n"
        "- If the current task is to build a page, app, tool, or feature, do not treat visual styling alone as completion when interactive behavior or functional logic is still missing.\n"
        "- Summarize only the concrete work actually completed and verified at the end of this execution step.\n\n"
        "## Context\n"
        f"Original user request:\n{user_input}\n\n"
        f"Confirmed delivery/workspace path:\n{workspace_context}\n\n"
        f"What is already available from previous peers:\n{available_outputs}\n\n"
        f"Available peers:\n{peer_directory}\n\n"
        f"Current task:\n{current_task_title}"
    )


PEER_HANDOFF_FINAL_RESPONSE_INSTRUCTION = (
    "Return ONLY one JSON object that matches one allowed action exactly. "
    "Do not use markdown. Do not output prose outside JSON. "
    "Never copy internal runtime markers into message, including TOOL_EXECUTION_NO_FINAL_ANSWER, TOOL_EXECUTION_BLOCKED, or Tool-enabled execution completed. "
    "The message must contain business context, not runtime diagnostics. "
    "The message must describe concrete completed work, not a generic progress update. "
    "If tool execution did not yield enough useful information, choose handoff or review when another peer can continue. "
    'If no clearly better peer exists for the remaining work, continue executing instead of handing off. '
    'If the current task is not fully complete, do not stop; either continue executing it yourself or hand it off to a more suitable peer. '
    'Make reasonable assumptions and continue when optional preferences or non-critical details are missing. '
)


def _build_peer_decision_prompt(
    *,
    user_input: str,
    current_task_title: str,
    peer_directory: str,
    available_outputs: str,
    workspace_context: str,
    execution_result: str,
    action_examples: str = "",
) -> str:
    return (
        "# Peer Handoff Decision\n"
        "You are the same peer agent that just executed the task. Now decide the next workflow action.\n"
        "Return exactly one JSON object and nothing else. Do not use markdown outside the JSON object.\n\n"
        "## Allowed actions\n"
        '- {"action":"continue","message":"<what you will continue doing next>"}\n'
        '- {"action":"handoff","target_agent_id":"<peer-id>","task_title":"<next task>","message":"<handoff reason>"}\n'
        '- {"action":"review","target_agent_id":"<peer-id>","task_title":"<review task>","message":"<review reason>"}\n'
        '- {"action":"complete","message":"<task result>"}\n'
        '- {"action":"respond_user","message":"<final user-facing answer>"}\n'
        '- {"action":"block","message":"<real blocker only>"}\n\n'
        "## Decision rules\n"
        "- Base the decision on the execution result and the original user request.\n"
        "- Use `complete` only if the original user request is fully satisfied by the accumulated outputs.\n"
        "- If the current step is done but the original user request still needs more work, use `handoff` to the most suitable peer with a concrete next task.\n"
        "- If another peer can materially improve the result, use `handoff` or `review` with a concrete task instead of doing everything yourself.\n"
        "- If you are still clearly the best peer and more work remains, use `continue` instead of `handoff` or `block`.\n"
        "- Use `respond_user` only when the user explicitly asked for a direct answer now, or when missing information creates a real blocker that prevents sensible progress.\n"
        "- Do not ask the user for optional preferences; make reasonable assumptions and continue via handoff when possible.\n"
        "- Do not claim a file, document, mockup, screenshot, or artifact was created unless the execution result or previous outputs actually support that claim.\n"
        "- Do not claim tool restrictions, permission errors, disabled capabilities, or environment limits unless the execution result or tool outputs explicitly show them.\n"
        "- Never target yourself with `handoff` or `review`; use `continue` when you should keep working.\n"
        "- Handoff and review task_title must preserve the confirmed delivery/workspace path when one exists.\n"
        "- If the next task requires filesystem work, repeat the confirmed delivery/workspace path explicitly in task_title or message, and describe paths as absolute paths.\n\n"
        "## Context\n"
        f"Original user request:\n{user_input}\n\n"
        f"Confirmed delivery/workspace path:\n{workspace_context}\n\n"
        f"Current task:\n{current_task_title}\n\n"
        f"What is already available from previous peers:\n{available_outputs}\n\n"
        f"Latest execution result:\n{execution_result}\n\n"
        f"Available peers:\n{peer_directory}\n\n"
        f"{action_examples}"
    )


# Repair layer prompt - converts invalid worker output to valid JSON action
def _build_repair_prompt(
    *,
    user_input: str,
    current_task_title: str,
    worker: AgentDefinition,
    workers: list[AgentDefinition],
    reports: list[str],
    raw_response: str,
    invalid_reason: str,
) -> str:
    peer_lines = "\n".join(
        f"- id={peer.id}; name={peer.name}; description={peer.description}"
        for peer in workers
        if peer.id != worker.id
    ) or "(no peers)"
    
    from .prompts import _available_outputs_block
    completed_log = _available_outputs_block(reports)

    return (
        "You are a workflow action repair layer.\n"
        "Your only job is to convert the worker output into ONE valid JSON action.\n"
        "Do not do the task again. Do not add markdown. Do not output prose outside JSON.\n\n"
        "Allowed actions:\n"
        '- {"action":"continue","message":"<what you will continue doing next>"}\n'
        '- {"action":"handoff","target_agent_id":"<peer-id>","task_title":"<next task>","message":"<handoff reason>"}\n'
        '- {"action":"review","target_agent_id":"<peer-id>","task_title":"<review task>","message":"<review reason>"}\n'
        '- {"action":"complete","message":"<task result>"}\n'
        '- {"action":"respond_user","message":"<final user-facing answer>"}\n'
        '- {"action":"block","message":"<real blocker only>"}\n\n'
        "Repair rules:\n"
        "- Preserve the original meaning as much as possible.\n"
        "- Never copy internal runtime markers into message, including TOOL_EXECUTION_NO_FINAL_ANSWER or TOOL_EXECUTION_BLOCKED.\n"
        "- If the original output includes prose outside the JSON object, discard the extra prose and keep only one valid JSON object.\n"
        "- If a message contains internal runtime status text, strip it out and rewrite the action with clean business-facing wording.\n"
        "- Rewrite weak messages into concrete summaries of completed work and remaining work when needed.\n"
        "- Prefer continuing with reasonable assumptions over asking the user for optional preferences.\n"
        "- Use respond_user only for a direct user-facing answer or a real blocker that truly needs user input.\n"
        "- If the same peer should keep working, prefer continue over block or self-handoff.\n"
        "- Do not preserve claims about created files, documents, mockups, screenshots, or artifacts unless the original output clearly states they were actually produced or verified.\n"
        "- Do not preserve vague completion claims for static shells, placeholder UI, or partial implementations when the current task still expects functional behavior.\n"
        "- If the output suggests another specialist should continue, prefer handoff.\n"
        "- If the output indicates a real blocker with no clear next peer, use block.\n"
        "- If the output contains a usable task result and no handoff is needed, use complete.\n"
        "- Never target the current worker with handoff or review.\n\n"
        f"Why the original output is invalid:\n{invalid_reason}\n\n"
        f"Current worker:\n- id={worker.id}; name={worker.name}; description={worker.description}\n\n"
        f"Available peers:\n{peer_lines}\n\n"
        f"Original user request:\n{user_input}\n\n"
        f"Current task title:\n{current_task_title}\n\n"
        f"What is already available from previous peers:\n{completed_log}\n\n"
        "Raw worker output to repair:\n"
        f"{raw_response}"
    )


def _available_outputs_block(reports: list[str]) -> str:
    """Build available outputs block for prompts."""
    if not reports:
        return "(nothing yet)"
    return "\n\n---\n\n".join(reports)


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


# Router prompt - for initial routing
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
