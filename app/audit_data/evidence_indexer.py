from __future__ import annotations

from pathlib import Path
from typing import Any

from .field_mapping import EVIDENCE_TYPE_BY_PREFIX



def build_evidence_index(evidence_root: Path) -> list[dict[str, Any]]:
    indexed: list[dict[str, Any]] = []
    for path in sorted(evidence_root.rglob("*.txt")):
        stem = path.stem
        prefix = stem.split("-", 1)[0] if "-" in stem else stem
        indexed.append(
            {
                "file_name": path.name,
                "evidence_code": stem,
                "evidence_type": EVIDENCE_TYPE_BY_PREFIX.get(prefix, "other"),
                "relative_path": path.relative_to(evidence_root).as_posix(),
                "exists": True,
            }
        )
    return indexed



def resolve_evidence_refs(evidence_index: list[dict[str, Any]], tokens: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    by_name = {str(item.get("file_name") or ""): item for item in evidence_index}
    refs: list[dict[str, Any]] = []
    missing: list[str] = []
    for token in tokens:
        normalized = token.strip()
        if not normalized:
            continue
        matched = by_name.get(normalized)
        if matched is None:
            missing.append(normalized)
            continue
        refs.append(dict(matched))
    return refs, missing
