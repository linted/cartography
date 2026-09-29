from dataclasses import dataclass

from cartography.models.core.common import PropertyRef
from cartography.models.core.nodes import CartographyNodeProperties
from cartography.models.core.nodes import CartographyNodeSchema
from cartography.models.core.relationships import CartographyRelProperties
from cartography.models.core.relationships import CartographyRelSchema
from cartography.models.core.relationships import LinkDirection
from cartography.models.core.relationships import make_target_node_matcher
from cartography.models.core.relationships import OtherRelationships
from cartography.models.core.relationships import TargetNodeMatcher


@dataclass(frozen=True)
class LangSmithProjectNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id", description="Tracing project UUID.")
    name: PropertyRef = PropertyRef("name", extra_index=True)
    description: PropertyRef = PropertyRef("description")
    start_time: PropertyRef = PropertyRef("start_time")
    end_time: PropertyRef = PropertyRef("end_time")
    trace_tier: PropertyRef = PropertyRef(
        "trace_tier", description="Project trace tier override, if set."
    )
    organization_default_trace_tier: PropertyRef = PropertyRef(
        "organization_default_trace_tier"
    )
    workspace_default_trace_tier: PropertyRef = PropertyRef(
        "workspace_default_trace_tier"
    )
    effective_trace_tier: PropertyRef = PropertyRef("effective_trace_tier")
    effective_longlived_ttl_days: PropertyRef = PropertyRef(
        "effective_longlived_ttl_days"
    )
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
class LangSmithProjectRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
class LangSmithProjectToOrganizationRel(CartographyRelSchema):
    target_node_label: str = "LangSmithOrganization"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("ORG_ID", set_in_kwargs=True)}
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "RESOURCE"
    properties: LangSmithProjectRelProperties = LangSmithProjectRelProperties()


@dataclass(frozen=True)
class LangSmithProjectToWorkspaceRel(CartographyRelSchema):
    target_node_label: str = "LangSmithWorkspace"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("tenant_id")}
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "CONTAINS"
    properties: LangSmithProjectRelProperties = LangSmithProjectRelProperties()


@dataclass(frozen=True)
class LangSmithProjectSchema(CartographyNodeSchema):
    label: str = "LangSmithProject"
    properties: LangSmithProjectNodeProperties = LangSmithProjectNodeProperties()
    sub_resource_relationship: LangSmithProjectToOrganizationRel = (
        LangSmithProjectToOrganizationRel()
    )
    other_relationships: OtherRelationships = OtherRelationships(
        [LangSmithProjectToWorkspaceRel()]
    )
