import requests

from cartography.intel.langsmith import deployments
from cartography.intel.langsmith import projects
from cartography.intel.langsmith.util import LangSmithPermissionError
from tests.data.langsmith.deployments import LANGSMITH_DEPLOYMENTS
from tests.data.langsmith.organizations import LANGSMITH_ORG_ID
from tests.data.langsmith.workspaces import LANGSMITH_WORKSPACES
from tests.data.langsmith.workspaces import WORKSPACE_DEV_ID
from tests.data.langsmith.workspaces import WORKSPACE_PROD_ID
from tests.integration.cartography.intel.langsmith.test_organizations import (
    _ensure_local_neo4j_has_test_organizations,
)
from tests.integration.cartography.intel.langsmith.test_workspaces import (
    _ensure_local_neo4j_has_test_workspaces,
)
from tests.integration.util import check_nodes
from tests.integration.util import check_rels

PROJECT_ID = LANGSMITH_DEPLOYMENTS[WORKSPACE_PROD_ID][0]["tracer_session_id"]


class _Client:
    def __init__(
        self,
        *,
        fail_workspace=None,
        timeout_workspace=None,
        empty_workspace=None,
        fail_settings=False,
    ):
        self.fail_workspace = fail_workspace
        self.timeout_workspace = timeout_workspace
        self.empty_workspace = empty_workspace
        self.fail_settings = fail_settings

    def get(self, path, *, tenant_id=None, org_id=None, params=None):
        if path == "/api/v1/sessions":
            if tenant_id == self.fail_workspace:
                raise LangSmithPermissionError("project listing unavailable")
            if tenant_id == self.timeout_workspace:
                raise requests.Timeout("project listing timed out")
            if tenant_id == self.empty_workspace:
                return []
            return (
                [
                    {
                        "id": PROJECT_ID,
                        "tenant_id": tenant_id,
                        "name": "Support traces",
                        "trace_tier": None,
                    }
                ]
                if tenant_id == WORKSPACE_PROD_ID
                else [
                    {
                        "id": "dev-project",
                        "tenant_id": tenant_id,
                        "name": "Dev traces",
                        "trace_tier": "shortlived",
                    }
                ]
            )
        if path == "/api/v1/orgs/ttl-settings":
            if self.fail_settings:
                raise LangSmithPermissionError("settings unavailable")
            assert org_id == LANGSMITH_ORG_ID
            return [
                {
                    "organization_id": org_id,
                    "tenant_id": None,
                    "default_trace_tier": "longlived",
                }
            ]
        if path == "/workspaces/current/ttl-settings":
            return {
                "tenant_id": tenant_id,
                "is_custom": False,
                "longlived_ttl_days": 365,
            }
        raise AssertionError(path)


def _parameters(update_tag):
    return {"UPDATE_TAG": update_tag, "ORG_ID": LANGSMITH_ORG_ID}


def test_project_relationships_retention_and_deployment_link(neo4j_session):
    # Arrange
    _ensure_local_neo4j_has_test_organizations(neo4j_session)
    _ensure_local_neo4j_has_test_workspaces(neo4j_session)

    # Act
    projects.sync(
        neo4j_session,
        _Client(),
        LANGSMITH_ORG_ID,
        LANGSMITH_WORKSPACES,
        _parameters(10),
    )
    deployment = deployments.transform_deployments(
        LANGSMITH_DEPLOYMENTS[WORKSPACE_PROD_ID]
    )
    deployments.load_deployments(neo4j_session, [], deployment, LANGSMITH_ORG_ID, 10)

    # Assert
    assert check_nodes(
        neo4j_session,
        "LangSmithProject",
        ["id", "trace_tier", "effective_trace_tier", "effective_longlived_ttl_days"],
    ) == {
        (PROJECT_ID, None, "longlived", 365),
        ("dev-project", "shortlived", "shortlived", None),
    }
    assert check_rels(
        neo4j_session,
        "LangSmithOrganization",
        "id",
        "LangSmithProject",
        "id",
        "RESOURCE",
        rel_direction_right=True,
    ) == {
        (LANGSMITH_ORG_ID, PROJECT_ID),
        (LANGSMITH_ORG_ID, "dev-project"),
    }
    assert check_rels(
        neo4j_session,
        "LangSmithWorkspace",
        "id",
        "LangSmithProject",
        "id",
        "CONTAINS",
        rel_direction_right=True,
    ) == {
        (WORKSPACE_PROD_ID, PROJECT_ID),
        (WORKSPACE_DEV_ID, "dev-project"),
    }
    assert check_rels(
        neo4j_session,
        "LangSmithDeployment",
        "id",
        "LangSmithProject",
        "id",
        "TRACES_TO",
        rel_direction_right=True,
    ) == {
        (deployment[0]["id"], PROJECT_ID),
    }


def test_incomplete_and_unauthorized_reads_preserve_projects(neo4j_session):
    # Arrange
    _ensure_local_neo4j_has_test_organizations(neo4j_session)
    _ensure_local_neo4j_has_test_workspaces(neo4j_session)
    projects.sync(
        neo4j_session,
        _Client(),
        LANGSMITH_ORG_ID,
        LANGSMITH_WORKSPACES,
        _parameters(10),
    )

    # Act
    projects.sync(
        neo4j_session,
        _Client(fail_workspace=WORKSPACE_PROD_ID),
        LANGSMITH_ORG_ID,
        LANGSMITH_WORKSPACES,
        _parameters(11),
    )
    projects.sync(
        neo4j_session,
        _Client(fail_settings=True),
        LANGSMITH_ORG_ID,
        LANGSMITH_WORKSPACES,
        _parameters(12),
    )
    projects.sync(
        neo4j_session,
        _Client(timeout_workspace=WORKSPACE_PROD_ID),
        LANGSMITH_ORG_ID,
        LANGSMITH_WORKSPACES,
        _parameters(13),
    )

    # Assert
    assert check_nodes(neo4j_session, "LangSmithProject", ["id"]) == {
        (PROJECT_ID,),
        ("dev-project",),
    }
    preserved = neo4j_session.run(
        "MATCH (p:LangSmithProject {id: $id}) RETURN p.lastupdated AS tag",
        id=PROJECT_ID,
    ).single()
    assert preserved["tag"] == 10


def test_complete_project_listing_cleans_up_stale_project(neo4j_session):
    # Arrange
    _ensure_local_neo4j_has_test_organizations(neo4j_session)
    _ensure_local_neo4j_has_test_workspaces(neo4j_session)
    projects.sync(
        neo4j_session,
        _Client(),
        LANGSMITH_ORG_ID,
        LANGSMITH_WORKSPACES,
        _parameters(10),
    )

    # Act
    projects.sync(
        neo4j_session,
        _Client(empty_workspace=WORKSPACE_PROD_ID),
        LANGSMITH_ORG_ID,
        LANGSMITH_WORKSPACES,
        _parameters(11),
    )

    # Assert
    assert check_nodes(neo4j_session, "LangSmithProject", ["id"]) == {("dev-project",)}
