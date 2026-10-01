from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import StreamingResponse

from .audit_data import analyze_a101_sample, load_a101_sample_bundle
from .audit_context.context_manager import audit_context_manager
from .audit_runtime import build_audit_context_runtime_graph, run_audit_context_runtime
from .audit_runtime.context_store import audit_context_runtime_store

from .runtime import llm_gateway
from .schemas import (
    AgentDefinition,
    AgentDefinitionCreate,
    AgentDefinitionUpdate,
    AppSettings,
    AuditFinding,
    AuditFindingCreate,
    AuditProject,
    AuditProjectCreate,
    Conversation,
    ConversationCreate,
    ConversationDetail,
    EvidenceItem,
    EvidenceItemCreate,
    ReviewComment,
    ReviewCommentCreate,
    RiskItem,
    RiskItemCreate,
    SharedAuditContext,
    SharedAuditContextUpdate,
    SkillDefinition,
    SkillDefinitionCreate,
    SkillInstallResponse,
    SkillSyncRequest,
    SkillSyncResponse,
    TraceEvent,
    WorkflowDefinition,
    WorkflowDefinitionCreate,
    WorkflowDefinitionUpdate,
    WorkflowGraph,
    WorkflowRunRequest,
    WorkflowRunResponse,
)
from .settings_bridge import (
    apply_structured_settings,
    normalize_structured_settings,
    settings,
)
from .skillhub_client import skillhub_client
from .store import store
from .workflows.planner_executor.workflow import build_planner_graph, run_planner_executor
from .workflows.peer_handoff.workflow import build_peer_handoff_graph, run_peer_handoff
from .workflows.router_specialists.workflow import build_router_graph, run_router_specialists
from .workflows.single_agent_chat.workflow import build_single_agent_graph, run_single_agent_chat
from .workflows.supervisor_dynamic.workflow import build_supervisor_graph, run_supervisor_dynamic


router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/settings", response_model=AppSettings)
def get_app_settings() -> AppSettings:
    structured = normalize_structured_settings(store.get_app_settings_payload())
    return AppSettings(
        model_profiles=structured["model_profiles"],  # type: ignore[arg-type]
        active_model_profile_id=str(structured["active_model_profile_id"] or "") or None,
        env_vars=structured["env_vars"],  # type: ignore[arg-type]
        env_path=settings.APP_ENV_PATH,
    )


@router.put("/settings", response_model=AppSettings)
def update_app_settings(payload: AppSettings) -> AppSettings:
    previous = store.get_app_settings_payload()
    current = normalize_structured_settings(payload.model_dump())
    store.save_app_settings_payload(current)
    apply_structured_settings(previous, current)
    llm_gateway.refresh_client()
    structured = normalize_structured_settings(store.get_app_settings_payload())
    return AppSettings(
        model_profiles=structured["model_profiles"],  # type: ignore[arg-type]
        active_model_profile_id=str(structured["active_model_profile_id"] or "") or None,
        env_vars=structured["env_vars"],  # type: ignore[arg-type]
        env_path=settings.APP_ENV_PATH,
    )


@router.get("/workflow-templates")
def list_workflow_templates():
    return store.get_templates()


@router.get("/audit-projects", response_model=list[AuditProject])
def list_audit_projects() -> list[AuditProject]:
    return store.list_audit_projects()


@router.post("/audit-projects", response_model=AuditProject)
def create_audit_project(payload: AuditProjectCreate) -> AuditProject:
    return store.create_audit_project(payload)


@router.get("/audit-projects/{project_id}", response_model=AuditProject)
def get_audit_project(project_id: str) -> AuditProject:
    project = store.get_audit_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Audit project not found.")
    return project


@router.get("/audit-contexts/{project_id}", response_model=SharedAuditContext)
def get_audit_context(project_id: str) -> SharedAuditContext:
    project = store.get_audit_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Audit project not found.")
    return store.ensure_audit_context(project_id)


@router.put("/audit-contexts/{project_id}", response_model=SharedAuditContext)
def update_audit_context(project_id: str, payload: SharedAuditContextUpdate) -> SharedAuditContext:
    project = store.get_audit_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Audit project not found.")
    return store.upsert_audit_context(project_id, payload)


@router.post("/audit-data/analyze-a101-sample")
def analyze_a101_sample_data() -> dict[str, object]:
    bundle = load_a101_sample_bundle()
    analysis = analyze_a101_sample(bundle)

    projects = store.list_audit_projects()
    project = next((item for item in projects if item.name == "XX公司2025年度审计"), projects[0] if projects else None)
    if project is None:
        raise HTTPException(status_code=404, detail="Audit project not found.")

    snapshot = audit_context_manager.load_context(project.id)
    project_snapshot = dict(snapshot.project_snapshot)
    project_snapshot.update(
        {
            "uploaded_files": analysis["uploaded_files"],
            "normalized_tables": analysis["normalized_tables"],
            "analysis_summary": analysis["analysis_summary"],
            "exception_candidates": analysis["exception_candidates"],
            "expected_comparison": analysis["expected_comparison"],
            "data_quality_warnings": analysis["data_quality_warnings"],
        }
    )

    audit_context_manager._store.persist_context(
        project.id,
        {
            "project_snapshot": project_snapshot,
            "risk_register": list(snapshot.risk_register),
            "evidence_index": analysis["evidence_index"],
            "agent_findings": list(snapshot.agent_findings)
            + [
                {
                    "agent_name": "a101_sample_analyzer",
                    "title": "A-101 sample package analysis completed",
                    "summary": json.dumps(analysis["analysis_summary"], ensure_ascii=False),
                    "risk_id": "A-101",
                    "exception_candidates": analysis["exception_candidates"],
                    "expected_comparison": analysis["expected_comparison"],
                }
            ],
            "open_questions": list(snapshot.open_questions),
            "next_actions": list(snapshot.next_actions),
        },
    )

    return {
        "analysis_summary": analysis["analysis_summary"],
        "exception_candidates": analysis["exception_candidates"],
        "expected_comparison": analysis["expected_comparison"],
        "evidence_index": analysis["evidence_index"],
        "data_quality_warnings": analysis["data_quality_warnings"],
    }


@router.get("/audit-context-file")
def get_audit_context_file() -> dict[str, object]:
    return {"content": audit_context_manager.readAuditContext()}


@router.get("/audit-events")
def get_audit_events() -> list[dict[str, object]]:
    return audit_context_manager.getAuditEvents()


@router.post("/audit-workspace/clear")
def clear_audit_workspace(project_id: str | None = None) -> dict[str, object]:
    legacy = audit_context_manager.clearAuditWorkspace()
    if project_id:
        audit_context_runtime_store.clear_runtime(project_id)
    return legacy


@router.get("/audit-runtime/{project_id}/trust")
def get_audit_trust(project_id: str) -> dict[str, object]:
    state = audit_context_runtime_store.get_latest_context(project_id)
    return {
        "trust_score": float(state.trust_score or 0.0),
        "validation_results": list(state.validation_results or []),
        "context_version": state.version,
    }


@router.post("/audit-runtime/{project_id}/trust/refresh")
def refresh_audit_trust(project_id: str) -> dict[str, object]:
    return audit_context_runtime_store.refresh_trust(project_id)


@router.get("/audit-runtime/{project_id}/pause")
def get_audit_pause(project_id: str) -> dict[str, object]:
    state = audit_context_runtime_store.get_latest_context(project_id)
    return {
        "paused": bool(state.paused),
        "pause_step": str(state.pause_step or ""),
        "pause_reason": str(state.pause_reason or ""),
        "review_required_items": list(state.review_required_items or []),
        "review_decisions": list(state.review_decisions or []),
    }


@router.post("/audit-runtime/{project_id}/resume")
def resume_audit_runtime(
    project_id: str,
    payload: dict[str, object] = Body(default_factory=dict),
) -> dict[str, object]:
    return audit_context_runtime_store.resume(project_id, dict(payload or {}))


@router.get("/audit-runtime/{project_id}/trail")
def get_audit_trail(project_id: str) -> list[dict[str, object]]:
    return audit_context_runtime_store.build_trail(project_id)


@router.get("/audit-runtime/{project_id}/review-gates")
def list_audit_review_gates(project_id: str) -> list[dict[str, object]]:
    return audit_context_runtime_store.list_review_gates(project_id)


@router.post("/audit-review-gates/{gate_id}/decision")
def post_audit_review_gate_decision(
    gate_id: str,
    payload: dict[str, object] = Body(default_factory=dict),
) -> dict[str, object]:
    """Submit a human review decision for a HumanReviewGate.

    Body shape:
      {
        "project_id": "...",
        "decision": "approved" | "need_more_evidence" | "rejected" | "escalated",
        "reviewer": "审计师",
        "comment": "..."
      }
    """
    body = dict(payload or {})
    project_id = str(body.get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required.")
    decision_kind = str(body.get("decision") or "").strip().lower()
    if decision_kind not in {"approved", "need_more_evidence", "rejected", "escalated"}:
        raise HTTPException(
            status_code=400,
            detail="decision must be one of: approved, need_more_evidence, rejected, escalated.",
        )
    try:
        result = audit_context_runtime_store.apply_gate_decision(
            project_id,
            gate_id,
            {
                "decision": decision_kind,
                "reviewer": body.get("reviewer") or "审计师",
                "comment": body.get("comment") or "",
            },
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "gate": result["gate"],
        "decision": result["decision"],
        "context_version_before": result["context_version_before"],
        "context_version_after": result["context_version_after"],
        "markdown": result["audit_md"],
        "event": result["event"].model_dump(),
    }


@router.get("/risks", response_model=list[RiskItem])
def list_risks(project_id: str | None = None) -> list[RiskItem]:
    return store.list_risk_items(project_id=project_id)


@router.post("/risks", response_model=RiskItem)
def create_risk(payload: RiskItemCreate) -> RiskItem:
    if store.get_audit_project(payload.project_id) is None:
        raise HTTPException(status_code=404, detail="Audit project not found.")
    return store.create_risk_item(payload)


@router.get("/evidence", response_model=list[EvidenceItem])
def list_evidence(project_id: str | None = None) -> list[EvidenceItem]:
    return store.list_evidence_items(project_id=project_id)


@router.post("/evidence", response_model=EvidenceItem)
def create_evidence(payload: EvidenceItemCreate) -> EvidenceItem:
    if store.get_audit_project(payload.project_id) is None:
        raise HTTPException(status_code=404, detail="Audit project not found.")
    return store.create_evidence_item(payload)


@router.get("/findings", response_model=list[AuditFinding])
def list_findings(project_id: str | None = None) -> list[AuditFinding]:
    return store.list_audit_findings(project_id=project_id)


@router.post("/findings", response_model=AuditFinding)
def create_finding(payload: AuditFindingCreate) -> AuditFinding:
    if store.get_audit_project(payload.project_id) is None:
        raise HTTPException(status_code=404, detail="Audit project not found.")
    return store.create_audit_finding(payload)


@router.get("/reviews", response_model=list[ReviewComment])
def list_reviews(project_id: str | None = None) -> list[ReviewComment]:
    return store.list_review_comments(project_id=project_id)


@router.post("/reviews", response_model=ReviewComment)
def create_review(payload: ReviewCommentCreate) -> ReviewComment:
    if store.get_audit_project(payload.project_id) is None:
        raise HTTPException(status_code=404, detail="Audit project not found.")
    return store.create_review_comment(payload)


@router.get("/skills", response_model=list[SkillDefinition])
def list_skills() -> list[SkillDefinition]:
    skills = store.list_skills()
    for skill in skills:
        skill.runtime_preflight = llm_gateway.build_skill_preflight(skill)
    return skills


@router.post("/skills", response_model=SkillDefinition)
def create_skill(payload: SkillDefinitionCreate) -> SkillDefinition:
    return store.create_skill(payload)


@router.post("/skills/{skill_id}/install", response_model=SkillInstallResponse)
def install_skill(skill_id: str) -> SkillInstallResponse:
    skill = store.get_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found.")

    provider = str(skill.source_provider or "").strip().lower()
    source_skill_id = str(skill.source_skill_id or "").strip() or None

    if provider == "skillhub":
        if not source_skill_id:
            raise HTTPException(status_code=400, detail="SkillHub skill missing source_skill_id.")
        try:
            remote = skillhub_client.fetch_skill_package(source_skill_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

        package_files = remote.package_files or {}
        if not package_files:
            raise HTTPException(
                status_code=409,
                detail=(
                    "SkillHub returned metadata only (no package files). "
                    "This skill cannot be truly installed yet."
                ),
            )

        installed = store.install_skill_package(
            skill_id=skill.id,
            name=remote.name or skill.name,
            description=remote.description or skill.description,
            instruction=remote.instruction or skill.instruction,
            tool=remote.tool,
            package_files=package_files,
        )
        if installed is None:
            raise HTTPException(status_code=404, detail="Skill not found.")

        return SkillInstallResponse(
            skill_id=installed.id,
            skill_name=installed.name,
            source_provider=installed.source_provider,
            source_skill_id=installed.source_skill_id,
            downloaded_files=len(package_files),
            tool_enabled=bool(installed.tool),
            message=f"Skill package downloaded: {len(package_files)} files.",
        )

    # Local/manual skill: package already exists in local store.
    return SkillInstallResponse(
        skill_id=skill.id,
        skill_name=skill.name,
        source_provider=skill.source_provider,
        source_skill_id=skill.source_skill_id,
        downloaded_files=0,
        tool_enabled=bool(skill.tool),
        message="Local skill is ready.",
    )


@router.post("/skills/sync", response_model=SkillSyncResponse)
def sync_skills(payload: SkillSyncRequest) -> SkillSyncResponse:
    if payload.provider != "skillhub":
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {payload.provider}")

    query = (payload.query or "").strip() or "search"

    try:
        remote_skills = skillhub_client.fetch_skills(query=query, limit=payload.limit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    imported, updated = store.upsert_marketplace_skills(
        source_provider="skillhub",
        skills=[
            {
                "source_skill_id": skill.source_skill_id,
                "name": skill.name,
                "description": skill.description,
                "instruction": skill.instruction,
                "tool": skill.tool,
                "package_files": skill.package_files,
            }
            for skill in remote_skills
        ],
    )

    return SkillSyncResponse(
        provider="skillhub",
        query=query,
        fetched=len(remote_skills),
        imported=imported,
        updated=updated,
    )


def _validate_skill_ids(skill_ids: list[str]) -> None:
    missing_ids = [skill_id for skill_id in skill_ids if store.get_skill(skill_id) is None]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"These skill IDs do not exist: {missing_ids}")


@router.get("/agents", response_model=list[AgentDefinition])
def list_agents() -> list[AgentDefinition]:
    return store.list_agents()


@router.post("/agents", response_model=AgentDefinition)
def create_agent(payload: AgentDefinitionCreate) -> AgentDefinition:
    _validate_skill_ids(payload.skill_ids)
    return store.create_agent(payload)


@router.put("/agents/{agent_id}", response_model=AgentDefinition)
def update_agent(agent_id: str, payload: AgentDefinitionUpdate) -> AgentDefinition:
    _validate_skill_ids(payload.skill_ids)
    updated = store.update_agent(agent_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return updated


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str) -> dict[str, bool]:
    agent = store.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")

    usage = store.agent_usage_workflows(agent_id)
    blocking = [w for w in usage if w.type != "single_agent_chat"]
    if blocking:
        names = ", ".join(workflow.name for workflow in blocking[:5])
        raise HTTPException(
            status_code=409,
            detail=f"Agent is still used by workflow(s): {names}",
        )

    for workflow in usage:
        if workflow.type == "single_agent_chat":
            store.delete_workflow(workflow.id)

    deleted = store.delete_agent(agent_id)
    return {"deleted": deleted}


@router.get("/workflows", response_model=list[WorkflowDefinition])
def list_workflows() -> list[WorkflowDefinition]:
    return store.list_workflows()


def _required_agent_count(workflow_type: str) -> int:
    for template in store.get_templates():
        if template.type == workflow_type:
            return template.required_agent_count
    return 2


@router.post("/workflows", response_model=WorkflowDefinition)
def create_workflow(payload: WorkflowDefinitionCreate) -> WorkflowDefinition:
    missing_ids = [agent_id for agent_id in payload.specialist_agent_ids if store.get_agent(agent_id) is None]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"These agent IDs do not exist: {missing_ids}")

    required_count = _required_agent_count(payload.type)
    if len(payload.specialist_agent_ids) < required_count:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{payload.type} requires at least {required_count} agents, "
                f"but got {len(payload.specialist_agent_ids)}."
            ),
        )
    return store.create_workflow(payload)


@router.put("/workflows/{workflow_id}", response_model=WorkflowDefinition)
def update_workflow(workflow_id: str, payload: WorkflowDefinitionUpdate) -> WorkflowDefinition:
    missing_ids = [agent_id for agent_id in payload.specialist_agent_ids if store.get_agent(agent_id) is None]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"These agent IDs do not exist: {missing_ids}")

    required_count = _required_agent_count(payload.type)
    if len(payload.specialist_agent_ids) < required_count:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{payload.type} requires at least {required_count} agents, "
                f"but got {len(payload.specialist_agent_ids)}."
            ),
        )

    updated = store.update_workflow(workflow_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return updated


@router.delete("/workflows/{workflow_id}")
def delete_workflow(workflow_id: str) -> dict[str, bool]:
    workflow = store.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    deleted = store.delete_workflow(workflow_id)
    return {"deleted": deleted}


def _resolve_agents(workflow: WorkflowDefinition) -> list[AgentDefinition]:
    agents = [store.get_agent(agent_id) for agent_id in workflow.specialist_agent_ids]
    return [agent for agent in agents if agent is not None]


@router.get("/workflows/{workflow_id}/graph", response_model=WorkflowGraph)
def get_workflow_graph(workflow_id: str) -> WorkflowGraph:
    workflow = store.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    agents = _resolve_agents(workflow)
    if workflow.type == "router_specialists":
        return build_router_graph(workflow, agents)
    if workflow.type == "planner_executor":
        return build_planner_graph(workflow, agents)
    if workflow.type == "audit_context_runtime":
        return build_audit_context_runtime_graph()
    if workflow.type == "supervisor_dynamic":
        return build_supervisor_graph(workflow, agents)
    if workflow.type == "single_agent_chat":
        return build_single_agent_graph(workflow, agents)
    if workflow.type == "peer_handoff":
        return build_peer_handoff_graph(workflow, agents)

    raise HTTPException(status_code=400, detail=f"Unsupported workflow type: {workflow.type}")


def _dispatch_run(
    workflow: WorkflowDefinition,
    user_input: str,
    conversation_id: str | None = None,
    on_event: Callable[[TraceEvent], None] | None = None,
    audit_context: dict[str, object] | None = None,
    on_audit_context_updated: Callable[[dict[str, object]], None] | None = None,
    on_runtime_event: Callable[[str, dict[str, object]], None] | None = None,
) -> WorkflowRunResponse:
    history = []
    if conversation_id:
        recent = store.get_recent_messages(conversation_id, limit=2)
        history = [{"role": msg.role, "content": msg.content} for msg in recent]

    if workflow.type == "router_specialists":
        return run_router_specialists(store, workflow, user_input, history=history, on_event=on_event)
    if workflow.type == "planner_executor":
        return run_planner_executor(store, workflow, user_input, history=history, on_event=on_event, audit_context=audit_context, on_audit_context_updated=on_audit_context_updated)
    if workflow.type == "audit_context_runtime":
        return run_audit_context_runtime(
            store,
            workflow,
            user_input,
            history=history,
            on_event=on_event,
            audit_context=audit_context,
            on_audit_context_updated=on_audit_context_updated,
            on_runtime_event=on_runtime_event,
        )
    if workflow.type == "supervisor_dynamic":
        return run_supervisor_dynamic(store, workflow, user_input, history=history, on_event=on_event)
    if workflow.type == "single_agent_chat":
        return run_single_agent_chat(store, workflow, user_input, history=history, on_event=on_event)
    if workflow.type == "peer_handoff":
        return run_peer_handoff(store, workflow, user_input, history=history, on_event=on_event)
    raise HTTPException(status_code=400, detail=f"Unsupported workflow type: {workflow.type}")


@router.post("/runs", response_model=WorkflowRunResponse)
def run_workflow(payload: WorkflowRunRequest) -> WorkflowRunResponse:
    workflow = store.get_workflow(payload.workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    conversation_id = payload.conversation_id
    if not conversation_id:
        conversation = store.create_conversation(
            ConversationCreate(workflow_id=payload.workflow_id)
        )
        conversation_id = conversation.id

    audit_context = None
    if payload.project_id and workflow.type == "planner_executor":
        from .audit_context.context_manager import audit_context_manager
        snapshot = audit_context_manager.load_context(payload.project_id)
        audit_context = {
            "project_id": payload.project_id,
            "context_id": payload.context_id or snapshot.context_id,
            "context_version": snapshot.context_version,
            "risk_scope": payload.risk_scope,
            "evidence_scope": payload.evidence_scope,
            "context_markdown": audit_context_manager.render_context_markdown(payload.project_id),
            "evidence_refs": payload.evidence_scope,
            "risk_id": payload.risk_scope[0] if payload.risk_scope else None,
            "project_snapshot": snapshot.project_snapshot,
            "evidence_index": snapshot.evidence_index,
            "agent_findings": snapshot.agent_findings,
            "next_actions": snapshot.next_actions,
        }
    elif payload.project_id and workflow.type == "audit_context_runtime":
        audit_context = {"project_id": payload.project_id}
    result = _dispatch_run(workflow, payload.user_input, conversation_id=conversation_id, audit_context=audit_context)

    store.create_message(
        conversation_id=conversation_id,
        role="user",
        content=payload.user_input,
    )
    store.create_message(
        conversation_id=conversation_id,
        role="assistant",
        content=result.assistant_message,
        agent_name=result.artifacts.route_agent_name,
    )

    if store.get_conversation(conversation_id).title is None:
        title = payload.user_input[:50] + ("..." if len(payload.user_input) > 50 else "")
        store.update_conversation_title(conversation_id, title)

    result.conversation_id = conversation_id
    return result


@router.post("/runs/stream")
def run_workflow_stream(payload: WorkflowRunRequest) -> StreamingResponse:
    workflow = store.get_workflow(payload.workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    conversation_id = payload.conversation_id
    if not conversation_id:
        conversation = store.create_conversation(
            ConversationCreate(workflow_id=payload.workflow_id)
        )
        conversation_id = conversation.id

    audit_context = None
    if payload.project_id and workflow.type == "planner_executor":
        from .audit_context.context_manager import audit_context_manager
        snapshot = audit_context_manager.load_context(payload.project_id)
        audit_context = {
            "project_id": payload.project_id,
            "context_id": payload.context_id or snapshot.context_id,
            "context_version": snapshot.context_version,
            "risk_scope": payload.risk_scope,
            "evidence_scope": payload.evidence_scope,
            "context_markdown": audit_context_manager.render_context_markdown(payload.project_id),
            "evidence_refs": payload.evidence_scope,
            "risk_id": payload.risk_scope[0] if payload.risk_scope else None,
            "project_snapshot": snapshot.project_snapshot,
            "evidence_index": snapshot.evidence_index,
            "agent_findings": snapshot.agent_findings,
            "next_actions": snapshot.next_actions,
        }
    elif payload.project_id and workflow.type == "audit_context_runtime":
        audit_context = {"project_id": payload.project_id}
    stream_queue: queue.Queue[tuple[str, dict | None]] = queue.Queue()

    def on_trace(event: TraceEvent) -> None:
        stream_queue.put(("trace", event.model_dump()))

    def on_audit_context_updated(payload: dict[str, object]) -> None:
        stream_queue.put(("audit_context_updated", payload))
        stream_queue.put(("audit_md_updated", payload))

    def on_runtime_event(event_name: str, body: dict[str, object]) -> None:
        # Forward generic audit-runtime events (human_review_required, etc.)
        # to the SSE stream. The frontend's runWorkflowStream() dispatches by
        # event name, so any new event added here just needs a matching
        # callback in api.js to be visible in the UI.
        stream_queue.put((event_name, body))

    def worker() -> None:
        try:
            result = _dispatch_run(
                workflow,
                payload.user_input,
                conversation_id=conversation_id,
                on_event=on_trace,
                audit_context=audit_context,
                on_audit_context_updated=on_audit_context_updated,
                on_runtime_event=on_runtime_event,
            )

            store.create_message(
                conversation_id=conversation_id,
                role="user",
                content=payload.user_input,
            )
            store.create_message(
                conversation_id=conversation_id,
                role="assistant",
                content=result.assistant_message,
                agent_name=result.artifacts.route_agent_name,
            )

            if store.get_conversation(conversation_id).title is None:
                title = payload.user_input[:50] + ("..." if len(payload.user_input) > 50 else "")
                store.update_conversation_title(conversation_id, title)

            result.conversation_id = conversation_id
            stream_queue.put(("final", result.model_dump()))
        except Exception as error:  # noqa: BLE001
            stream_queue.put(("error", {"message": str(error)}))
        finally:
            stream_queue.put(("end", None))

    threading.Thread(target=worker, daemon=True).start()

    def event_stream():
        while True:
            event_name, body = stream_queue.get()
            if event_name == "end":
                yield "event: end\ndata: {}\n\n"
                break
            yield f"event: {event_name}\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============ Conversation API ============

@router.get("/conversations", response_model=list[Conversation])
def list_conversations(workflow_id: str | None = None) -> list[Conversation]:
    return store.list_conversations(workflow_id=workflow_id)


@router.post("/conversations", response_model=Conversation)
def create_conversation(payload: ConversationCreate) -> Conversation:
    workflow = store.get_workflow(payload.workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return store.create_conversation(payload)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str) -> ConversationDetail:
    conversation = store.get_conversation_with_messages(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, bool]:
    deleted = store.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"deleted": True}
