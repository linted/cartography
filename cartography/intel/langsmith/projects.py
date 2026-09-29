import logging
from typing import Any

import neo4j
import requests

from cartography.client.core.tx import load
from cartography.graph.job import GraphJob
from cartography.intel.langsmith.util import LangSmithClient
from cartography.intel.langsmith.util import LangSmithPermissionError
from cartography.models.langsmith.project import LangSmithProjectSchema
from cartography.util import timeit

logger = logging.getLogger(__name__)
_PAGE_SIZE = 100
_TRACE_TIERS = {"longlived", "shortlived"}


def get_projects(client: LangSmithClient, workspace_id: str) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = client.get(
            "/api/v1/sessions",
            tenant_id=workspace_id,
            params={"limit": _PAGE_SIZE, "offset": offset},
        )
        if not isinstance(page, list) or any(
            not isinstance(item, dict)
            or not item.get("id")
            or item.get("tenant_id") != workspace_id
            for item in page
        ):
            raise ValueError("Invalid LangSmith project listing")
        projects.extend(page)
        if len(page) < _PAGE_SIZE:
            return projects
        offset += len(page)


def transform_projects(
    raw: list[dict[str, Any]],
    settings: list[dict[str, Any]],
    org_id: str,
    effective_ttl_days: dict[str, int],
) -> list[dict[str, Any]]:
    org_setting = next(
        (
            row
            for row in settings
            if row.get("tenant_id") is None and row.get("organization_id") == org_id
        ),
        {},
    )
    workspace_settings = {
        row["tenant_id"]: row
        for row in settings
        if row.get("tenant_id") and row.get("organization_id") == org_id
    }
    org_default = org_setting.get("default_trace_tier")
    projects = []
    for project in raw:
        workspace_default = workspace_settings.get(project["tenant_id"], {}).get(
            "default_trace_tier"
        )
        override = project.get("trace_tier")
        for tier in (override, workspace_default, org_default):
            if tier is not None and tier not in _TRACE_TIERS:
                raise ValueError("Unknown LangSmith trace tier")
        effective = override or workspace_default or org_default
        projects.append(
            {
                "id": project["id"],
                "tenant_id": project["tenant_id"],
                "name": project.get("name"),
                "description": project.get("description"),
                "start_time": project.get("start_time"),
                "end_time": project.get("end_time"),
                "trace_tier": override,
                "organization_default_trace_tier": org_default,
                "workspace_default_trace_tier": workspace_default,
                "effective_trace_tier": effective,
                "effective_longlived_ttl_days": (
                    effective_ttl_days.get(project["tenant_id"])
                    if effective == "longlived"
                    else None
                ),
            }
        )
    return projects


@timeit
def sync(
    neo4j_session: neo4j.Session,
    client: LangSmithClient,
    org_id: str,
    workspaces: list[dict[str, Any]],
    common_job_parameters: dict[str, Any],
) -> None:
    raw = []
    complete = True
    for workspace in workspaces:
        try:
            raw.extend(get_projects(client, workspace["id"]))
        except (LangSmithPermissionError, requests.RequestException, ValueError) as err:
            logger.warning(
                "Skipping LangSmith projects for workspace %s: %s", workspace["id"], err
            )
            complete = False

    try:
        settings = client.get("/api/v1/orgs/ttl-settings", org_id=org_id)
        if not isinstance(settings, list) or any(
            not isinstance(row, dict) for row in settings
        ):
            raise ValueError("Invalid LangSmith retention settings")
    except (LangSmithPermissionError, requests.RequestException, ValueError) as err:
        logger.warning(
            "Skipping LangSmith projects for organization %s: %s", org_id, err
        )
        return

    effective_ttl_days: dict[str, int] = {}
    for workspace in workspaces:
        try:
            ttl = client.get(
                "/workspaces/current/ttl-settings", tenant_id=workspace["id"]
            )
            if isinstance(ttl, dict) and isinstance(ttl.get("longlived_ttl_days"), int):
                effective_ttl_days[workspace["id"]] = ttl["longlived_ttl_days"]
        except (LangSmithPermissionError, requests.RequestException) as err:
            logger.warning(
                "Could not read effective LangSmith retention for workspace %s: %s",
                workspace["id"],
                err,
            )

    try:
        projects = transform_projects(raw, settings, org_id, effective_ttl_days)
    except ValueError as err:
        logger.warning(
            "Skipping LangSmith projects for organization %s: %s", org_id, err
        )
        return
    load(
        neo4j_session,
        LangSmithProjectSchema(),
        projects,
        lastupdated=common_job_parameters["UPDATE_TAG"],
        ORG_ID=org_id,
    )
    if complete:
        GraphJob.from_node_schema(LangSmithProjectSchema(), common_job_parameters).run(
            neo4j_session
        )
    else:
        logger.warning(
            "Skipping LangSmith project cleanup for organization %s: collection was incomplete",
            org_id,
        )
