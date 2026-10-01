from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..schemas import WorkflowEdge, WorkflowGraph, WorkflowNode


_VALID_KINDS = {"start", "logic", "agent", "final", "end", "group"}


def _normalize_node_id(node_id: str) -> str:
    if node_id in {"__start__", "START"}:
        return "start"
    if node_id in {"__end__", "END"}:
        return "end"
    return node_id


def _infer_kind(node_id: str, metadata: Mapping[str, Any]) -> str:
    kind = metadata.get("kind")
    if isinstance(kind, str) and kind in _VALID_KINDS:
        return kind
    if node_id == "start":
        return "start"
    if node_id == "end":
        return "end"
    return "logic"


def _infer_label(node_id: str, kind: str, metadata: Mapping[str, Any], raw_node: Mapping[str, Any]) -> str:
    label = metadata.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()

    if kind == "start":
        return "START"
    if kind == "end":
        return "END"

    data = raw_node.get("data")
    if isinstance(data, dict):
        name = data.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(data, str) and data.strip():
        return data.strip()
    return node_id


def workflow_graph_from_compiled(compiled_app: Any) -> WorkflowGraph:
    raw = compiled_app.get_graph().to_json()
    raw_nodes = raw.get("nodes", [])
    raw_edges = raw.get("edges", [])

    nodes: list[WorkflowNode] = []
    seen: set[str] = set()
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        raw_id = str(raw_node.get("id", "")).strip()
        if not raw_id:
            continue
        node_id = _normalize_node_id(raw_id)
        if node_id in seen:
            continue
        seen.add(node_id)

        metadata_obj = raw_node.get("metadata")
        metadata = metadata_obj if isinstance(metadata_obj, dict) else {}
        kind = _infer_kind(node_id, metadata)
        label = _infer_label(node_id, kind, metadata, raw_node)
        nodes.append(WorkflowNode(id=node_id, label=label, kind=kind))

    edges: list[WorkflowEdge] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        source = _normalize_node_id(str(raw_edge.get("source", "")).strip())
        target = _normalize_node_id(str(raw_edge.get("target", "")).strip())
        if not source or not target:
            continue

        data = raw_edge.get("data")
        label: str | None
        if data is None:
            label = None
        elif isinstance(data, str):
            label = data
        else:
            label = str(data)
        edges.append(WorkflowEdge(source=source, target=target, label=label))

    return WorkflowGraph(nodes=nodes, edges=edges)
