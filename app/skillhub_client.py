from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

from .settings_bridge import settings


@dataclass(slots=True)
class MarketplaceSkill:
    source_skill_id: str
    name: str
    description: str
    instruction: str
    tool: dict[str, Any] | None = None
    package_files: dict[str, str] | None = None


class SkillHubClient:
    def __init__(self) -> None:
        raw_base = getattr(settings, "SKILLHUB_BASE_URL", "https://www.skillhub.club/api/v1").rstrip("/")
        if raw_base.endswith("/api/v1"):
            self.base_url = raw_base
        else:
            self.base_url = f"{raw_base}/api/v1"
        self.api_key = getattr(settings, "SKILLHUB_API_KEY", "")
        self.timeout = int(getattr(settings, "SKILLHUB_TIMEOUT_SECONDS", 20))

    def fetch_skills(self, query: str | None = None, limit: int = 40) -> list[MarketplaceSkill]:
        if not self.api_key:
            raise ValueError("SKILLHUB_API_KEY is not configured.")

        normalized_query = (query or "").strip()
        limit = max(1, min(limit, 100))

        errors: list[str] = []
        for endpoint, method, payload in self._candidate_requests(normalized_query, limit):
            try:
                response_payload = self._fetch_json(endpoint=endpoint, method=method, payload=payload)
                skills = self._extract_skills(response_payload, fallback_query=normalized_query)
                if skills:
                    return skills
            except Exception as error:  # noqa: BLE001
                errors.append(f"{method} {endpoint}: {error}")
                continue

        detail = "; ".join(errors[:3]) if errors else "no endpoint response"
        raise RuntimeError(f"Failed to fetch skills from SkillHub API. {detail}")

    def fetch_skill_package(self, source_skill_id: str) -> MarketplaceSkill:
        if not self.api_key:
            raise ValueError("SKILLHUB_API_KEY is not configured.")

        skill_id = str(source_skill_id or "").strip()
        if not skill_id:
            raise ValueError("source_skill_id is required.")

        encoded_id = quote(skill_id, safe="")
        errors: list[str] = []
        candidates: list[tuple[str, str, dict[str, Any] | None]] = [
            (f"/skills/{encoded_id}", "GET", None),
            (f"/skills/{encoded_id}/detail", "GET", None),
            (f"/skills/{encoded_id}/package", "GET", None),
            (f"/skills/detail?{urlencode({'id': skill_id})}", "GET", None),
            (f"/skills/package?{urlencode({'id': skill_id})}", "GET", None),
            (
                "/skills/search",
                "POST",
                {
                    "query": skill_id,
                    "limit": 20,
                    "method": "hybrid",
                },
            ),
        ]

        for endpoint, method, payload in candidates:
            try:
                response_payload = self._fetch_json(endpoint=endpoint, method=method, payload=payload)
                row = self._extract_skill_row_by_id(response_payload, skill_id)
                if row is None:
                    continue
                normalized = self._normalize_skill(row)
                if normalized is not None:
                    return normalized
            except Exception as error:  # noqa: BLE001
                errors.append(f"{method} {endpoint}: {error}")
                continue

        detail = "; ".join(errors[:4]) if errors else "no endpoint response"
        raise RuntimeError(f"Failed to fetch skill package for '{skill_id}'. {detail}")

    def _candidate_requests(
        self,
        query: str,
        limit: int,
    ) -> list[tuple[str, str, dict[str, Any] | None]]:
        params_catalog = {"limit": limit, "sort": "composite"}
        if query:
            params_catalog["q"] = query

        return [
            (
                "/skills/search",
                "POST",
                {
                    "query": query or "search",
                    "limit": limit,
                    "method": "hybrid",
                },
            ),
            (f"/skills/catalog?{urlencode(params_catalog)}", "GET", None),
        ]

    def _fetch_json(
        self,
        endpoint: str,
        method: str,
        payload: dict[str, Any] | None,
    ) -> Any:
        url = urljoin(f"{self.base_url}/", endpoint.lstrip("/"))
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            url=url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            data=body,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as error:
            detail = ""
            try:
                detail = error.read().decode("utf-8")
            except Exception:  # noqa: BLE001
                detail = error.reason if hasattr(error, "reason") else ""
            raise RuntimeError(f"HTTP {error.code} {detail}".strip()) from error
        except URLError as error:
            raise RuntimeError(f"Network error: {error.reason}") from error

        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Invalid JSON response: {raw[:200]}") from error

    def _extract_skills(self, payload: Any, fallback_query: str) -> list[MarketplaceSkill]:
        rows = self._extract_rows(payload)

        skills: list[MarketplaceSkill] = []
        seen: set[str] = set()
        query_token = fallback_query.lower()

        for row in rows:
            normalized = self._normalize_skill(row)
            if not normalized:
                continue

            if query_token:
                haystack = f"{normalized.name} {normalized.description}".lower()
                if query_token not in haystack:
                    continue

            if normalized.source_skill_id in seen:
                continue

            seen.add(normalized.source_skill_id)
            skills.append(normalized)

        return skills

    def _extract_rows(self, payload: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if isinstance(payload, list):
            rows = [row for row in payload if isinstance(row, dict)]
        elif isinstance(payload, dict):
            for key in ("items", "data", "results", "skills", "list"):
                value = payload.get(key)
                if isinstance(value, list):
                    rows = [row for row in value if isinstance(row, dict)]
                    break
                if isinstance(value, dict):
                    nested = value.get("items") or value.get("results") or value.get("skills")
                    if isinstance(nested, list):
                        rows = [row for row in nested if isinstance(row, dict)]
                        break
            if not rows and any(key in payload for key in ("id", "skill_id", "name", "title", "description")):
                rows = [payload]
        return rows

    def _extract_skill_row_by_id(self, payload: Any, source_skill_id: str) -> dict[str, Any] | None:
        rows = self._extract_rows(payload)
        if not rows:
            return None

        target = str(source_skill_id or "").strip()
        for row in rows:
            row_id = str(
                row.get("id")
                or row.get("skill_id")
                or row.get("uuid")
                or row.get("slug")
                or ""
            ).strip()
            if row_id and row_id == target:
                return row

        if len(rows) == 1:
            return rows[0]
        return None

    def _normalize_skill(self, row: dict[str, Any]) -> MarketplaceSkill | None:
        source_skill_id = str(
            row.get("id")
            or row.get("skill_id")
            or row.get("uuid")
            or row.get("slug")
            or row.get("name")
            or ""
        ).strip()
        if not source_skill_id:
            return None

        name = str(row.get("name") or row.get("title") or source_skill_id).strip()
        if not name:
            return None

        description = str(
            row.get("description")
            or row.get("summary")
            or row.get("tagline")
            or f"Imported from SkillHub: {name}"
        ).strip()
        instruction = str(
            row.get("instruction")
            or row.get("prompt")
            or row.get("system_prompt")
            or row.get("content")
            or row.get("usage")
            or (
                f"You can use the '{name}' skill when relevant. "
                "If external tools are needed, ask user to configure access first."
            )
        ).strip()

        if len(description) > 200:
            description = f"{description[:197].rstrip()}..."

        tool = self._extract_tool_config(row)
        package_files = self._extract_package_files(row)

        return MarketplaceSkill(
            source_skill_id=source_skill_id,
            name=name[:80],
            description=description,
            instruction=instruction,
            tool=tool,
            package_files=package_files,
        )

    def _extract_tool_config(self, row: dict[str, Any]) -> dict[str, Any] | None:
        tool_candidate = row.get("tool")
        if isinstance(tool_candidate, dict):
            command = tool_candidate.get("command")
            if isinstance(command, list) and command:
                return {
                    "name": str(tool_candidate.get("name") or row.get("name") or "tool").strip(),
                    "description": str(tool_candidate.get("description") or row.get("description") or "").strip(),
                    "input_schema": tool_candidate.get("input_schema") or {
                        "type": "object",
                        "properties": {},
                    },
                    "command": [str(item) for item in command],
                    "timeout_seconds": int(tool_candidate.get("timeout_seconds") or 20),
                }

        command = row.get("command") or row.get("run_command") or row.get("exec")
        if isinstance(command, list) and command:
            return {
                "name": str(row.get("name") or "tool").strip(),
                "description": str(row.get("description") or "").strip(),
                "input_schema": {"type": "object", "properties": {}},
                "command": [str(item) for item in command],
                "timeout_seconds": 20,
            }
        if isinstance(command, str) and command.strip():
            return {
                "name": str(row.get("name") or "tool").strip(),
                "description": str(row.get("description") or "").strip(),
                "input_schema": {"type": "object", "properties": {}},
                "command": command.strip().split(),
                "timeout_seconds": 20,
            }

        mcp_candidate = row.get("mcp") or row.get("mcp_server")
        if isinstance(mcp_candidate, dict):
            cmd = mcp_candidate.get("command")
            args = mcp_candidate.get("args")
            if isinstance(cmd, str) and cmd.strip():
                command_list = [cmd.strip()]
                if isinstance(args, list):
                    command_list.extend(str(item) for item in args)
                return {
                    "name": str(mcp_candidate.get("name") or row.get("name") or "tool").strip(),
                    "description": str(mcp_candidate.get("description") or row.get("description") or "").strip(),
                    "input_schema": {"type": "object", "properties": {}},
                    "command": command_list,
                    "timeout_seconds": 30,
                }

        return None

    def _extract_package_files(self, row: dict[str, Any]) -> dict[str, str] | None:
        collected: dict[str, str] = {}

        files = row.get("files")
        if isinstance(files, list):
            for item in files:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path") or "").strip()
                content = item.get("content")
                if not path or not isinstance(content, str):
                    continue
                collected[path] = content

        package = row.get("package")
        if isinstance(package, dict):
            for path, content in package.items():
                if not isinstance(path, str) or not isinstance(content, str):
                    continue
                if not path.strip():
                    continue
                collected[path] = content

        skill_md = row.get("skill_md") or row.get("skill_markdown")
        if isinstance(skill_md, str) and skill_md.strip():
            collected.setdefault("SKILL.md", skill_md)

        script = row.get("script") or row.get("script_content")
        if isinstance(script, str) and script.strip():
            collected.setdefault("scripts/run.py", script)

        return collected or None


skillhub_client = SkillHubClient()
