from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


WorkflowType = Literal[
    "router_specialists",
    "planner_executor",
    "audit_context_runtime",
    "supervisor_dynamic",
    "single_agent_chat",
    "peer_handoff",
]
BuiltinCapability = Literal[
    "filesystem",
    "fs_list",
    "fs_read",
    "fs_write",
]
TraceEventType = Literal[
    "run_started",
    "node_entered",
    "node_exited",
    "route_selected",
    "message_generated",
    "state_updated",
    "run_finished",
    "audit_structured_output",
    "audit_context_loaded",
    "audit_context_patch_applied",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1)


class SkillDefinition(SkillDefinitionCreate):
    id: str
    source_provider: str | None = None
    source_skill_id: str | None = None
    tool: dict[str, Any] | None = None
    local_path: str | None = None
    runtime_preflight: dict[str, Any] | None = None


class SkillSyncRequest(BaseModel):
    provider: Literal["skillhub"] = "skillhub"
    query: str | None = Field(default="search", max_length=80)
    limit: int = Field(default=40, ge=1, le=100)


class SkillSyncResponse(BaseModel):
    provider: str
    query: str
    fetched: int
    imported: int
    updated: int


class SkillInstallResponse(BaseModel):
    skill_id: str
    skill_name: str
    source_provider: str | None = None
    source_skill_id: str | None = None
    downloaded_files: int = 0
    tool_enabled: bool = False
    message: str


class AgentDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=200)
    system_prompt: str = Field(min_length=1)
    model: str | None = None
    skill_ids: list[str] = Field(default_factory=list)
    builtin_capabilities: list[BuiltinCapability] = Field(default_factory=list)


class AgentDefinition(AgentDefinitionCreate):
    id: str


class AgentDefinitionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=200)
    system_prompt: str = Field(min_length=1)
    model: str | None = None
    skill_ids: list[str] = Field(default_factory=list)
    builtin_capabilities: list[BuiltinCapability] = Field(default_factory=list)


class WorkflowDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: WorkflowType
    specialist_agent_ids: list[str] = Field(default_factory=list)
    router_prompt: str = Field(
        default="You are a workflow router. Pick the best specialist based on user intent."
    )
    finalizer_enabled: bool = True


class WorkflowDefinition(WorkflowDefinitionCreate):
    id: str


class WorkflowDefinitionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: WorkflowType
    specialist_agent_ids: list[str] = Field(default_factory=list)
    router_prompt: str = Field(
        default="You are a workflow router. Pick the best specialist based on user intent."
    )
    finalizer_enabled: bool = True


class WorkflowTemplate(BaseModel):
    type: WorkflowType
    label: str
    description: str
    required_agent_count: int


class WorkflowNode(BaseModel):
    id: str
    label: str
    kind: Literal["start", "logic", "agent", "final", "end", "group"]
    parent_id: str | None = None
    subtitle: str | None = None
    node_type: str | None = None


class WorkflowEdge(BaseModel):
    source: str
    target: str
    label: str | None = None


class WorkflowGraph(BaseModel):
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]


class TraceEvent(BaseModel):
    type: TraceEventType
    title: str
    detail: str
    at: str = Field(default_factory=utc_now_iso)
    payload: dict[str, Any] = Field(default_factory=dict)


class RunArtifacts(BaseModel):
    route_agent_id: str | None = None
    route_agent_name: str | None = None
    route_reason: str | None = None
    specialist_answer: str | None = None
    final_answer: str | None = None
    audit_summary: dict[str, Any] = Field(default_factory=dict)
    task_reports: list[Any] = Field(default_factory=list)
    structured_mode: bool = False
    risk_id: str | None = None


class WorkflowRunRequest(BaseModel):
    workflow_id: str
    user_input: str = Field(min_length=1)
    conversation_id: str | None = None
    project_id: str | None = None
    context_id: str | None = None
    risk_scope: list[str] = Field(default_factory=list)
    evidence_scope: list[str] = Field(default_factory=list)


class WorkflowRunResponse(BaseModel):
    workflow_id: str
    user_input: str
    assistant_message: str
    trace: list[TraceEvent]
    graph: WorkflowGraph
    artifacts: RunArtifacts
    conversation_id: str | None = None


class ConversationCreate(BaseModel):
    workflow_id: str = Field(min_length=1)


class Conversation(ConversationCreate):
    id: str
    title: str | None = None
    created_at: str
    updated_at: str


class Message(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    agent_name: str | None = None
    created_at: str


class ConversationDetail(Conversation):
    messages: list[Message] = Field(default_factory=list)


class ModelProfile(BaseModel):
    id: str
    provider: str = "custom"
    name: str = "Default"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"


class EnvVarEntry(BaseModel):
    key: str = Field(min_length=1)
    value: str = ""


class AppSettings(BaseModel):
    model_profiles: list[ModelProfile] = Field(default_factory=list)
    active_model_profile_id: str | None = None
    env_vars: list[EnvVarEntry] = Field(default_factory=list)
    env_path: str = ""


class AuditProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    audit_period: str = Field(min_length=1, max_length=80)
    industry: str = Field(min_length=1, max_length=80)
    materiality: float = Field(ge=0)
    status: str = Field(default="active", min_length=1, max_length=40)


class AuditProject(AuditProjectCreate):
    id: str
    created_at: str
    updated_at: str


class SharedAuditContextUpdate(BaseModel):
    project_snapshot: dict[str, Any] = Field(default_factory=dict)
    risk_register: list[dict[str, Any]] = Field(default_factory=list)
    evidence_index: list[dict[str, Any]] = Field(default_factory=list)
    agent_findings: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)


class SharedAuditContext(SharedAuditContextUpdate):
    id: str
    project_id: str
    created_at: str
    updated_at: str


class RiskItemCreate(BaseModel):
    project_id: str = Field(min_length=1)
    risk_code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    related_accounts: list[str] = Field(default_factory=list)
    assertions: list[str] = Field(default_factory=list)
    risk_level: str = Field(default="medium", min_length=1, max_length=20)
    status: str = Field(default="open", min_length=1, max_length=20)


class RiskItem(RiskItemCreate):
    id: str
    created_at: str
    updated_at: str


class EvidenceItemCreate(BaseModel):
    project_id: str = Field(min_length=1)
    risk_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    evidence_type: str = Field(default="document", min_length=1, max_length=40)
    source: str = Field(default="", max_length=200)
    reference_path: str = Field(default="", max_length=500)
    summary: str = Field(default="", max_length=4000)
    status: str = Field(default="collected", min_length=1, max_length=30)


class EvidenceItem(EvidenceItemCreate):
    id: str
    created_at: str
    updated_at: str


class AuditFindingCreate(BaseModel):
    project_id: str = Field(min_length=1)
    risk_id: str | None = None
    evidence_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    severity: str = Field(default="medium", min_length=1, max_length=20)
    status: str = Field(default="open", min_length=1, max_length=20)
    owner_agent: str | None = None


class AuditFinding(AuditFindingCreate):
    id: str
    created_at: str
    updated_at: str


class ReviewCommentCreate(BaseModel):
    project_id: str = Field(min_length=1)
    finding_id: str | None = None
    evidence_id: str | None = None
    comment: str = Field(min_length=1, max_length=4000)
    reviewer: str = Field(default="", max_length=120)
    status: str = Field(default="open", min_length=1, max_length=20)


class ReviewComment(ReviewCommentCreate):
    id: str
    created_at: str
    updated_at: str


class RunHistory(BaseModel):
    id: str
    project_id: str | None = None
    workflow_id: str
    conversation_id: str | None = None
    user_input: str
    assistant_message: str = ""
    status: str = Field(default="completed")
    started_at: str
    finished_at: str | None = None


class TraceRecord(BaseModel):
    id: str
    run_id: str
    project_id: str | None = None
    event_type: str
    title: str
    detail: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str
