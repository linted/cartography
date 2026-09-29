import pytest

from cartography.intel.langsmith import projects


class _Pages:
    def __init__(self):
        self.offsets = []

    def get(self, path, *, tenant_id, params):
        assert path == "/api/v1/sessions"
        assert params["limit"] == 100
        self.offsets.append(params["offset"])
        count = 100 if params["offset"] == 0 else 1
        return [
            {"id": f"p-{params['offset'] + i}", "tenant_id": tenant_id}
            for i in range(count)
        ]


def test_projects_are_paginated_without_traces():
    # Arrange
    client = _Pages()

    # Act
    result = projects.get_projects(client, "workspace")

    # Assert
    assert len(result) == 101
    assert client.offsets == [0, 100]


def test_wrong_workspace_or_malformed_page_is_incomplete():
    # Arrange
    class _BadPage:
        def get(self, *args, **kwargs):
            return [{"id": "p", "tenant_id": "other"}]

    # Act and assert
    with pytest.raises(ValueError, match="Invalid LangSmith project listing"):
        projects.get_projects(_BadPage(), "workspace")


def test_retention_override_workspace_and_organization_defaults():
    # Arrange
    raw = [
        {"id": "override", "tenant_id": "w1", "trace_tier": "shortlived"},
        {"id": "workspace", "tenant_id": "w1", "trace_tier": None},
        {"id": "organization", "tenant_id": "w2", "trace_tier": None},
    ]
    settings = [
        {
            "organization_id": "org",
            "tenant_id": None,
            "default_trace_tier": "longlived",
        },
        {
            "organization_id": "org",
            "tenant_id": "w1",
            "default_trace_tier": "shortlived",
        },
    ]

    # Act
    result = {
        row["id"]: row
        for row in projects.transform_projects(
            raw, settings, "org", {"w1": 365, "w2": 400}
        )
    }

    # Assert
    assert result["override"]["trace_tier"] == "shortlived"
    assert result["workspace"]["trace_tier"] is None
    assert result["workspace"]["workspace_default_trace_tier"] == "shortlived"
    assert result["workspace"]["effective_trace_tier"] == "shortlived"
    assert result["organization"]["organization_default_trace_tier"] == "longlived"
    assert result["organization"]["effective_trace_tier"] == "longlived"
    assert result["organization"]["effective_longlived_ttl_days"] == 400
    assert result["workspace"]["effective_longlived_ttl_days"] is None


def test_no_readable_default_does_not_invent_effective_retention():
    # Arrange
    raw = [{"id": "p", "tenant_id": "w", "trace_tier": None}]

    # Act
    project = projects.transform_projects(raw, [], "org", {})[0]

    # Assert
    assert project["trace_tier"] is None
    assert project["effective_trace_tier"] is None
    assert project["effective_longlived_ttl_days"] is None
