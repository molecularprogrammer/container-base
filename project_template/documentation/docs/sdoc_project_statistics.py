from collections import Counter
from typing import Iterable, Optional
from urllib.parse import quote

from markupsafe import Markup

from strictdoc.backend.sdoc.models.node import SDocNode
from strictdoc.core.document_iterator import SDocDocumentIterator
from strictdoc.core.project_config import ProjectConfig
from strictdoc.core.traceability_index import TraceabilityIndex
from strictdoc.export.html.html_templates import HTMLTemplates
from strictdoc.export.html.renderers.link_renderer import LinkRenderer
from strictdoc.features.project_statistics.metric import Metric, MetricSection
from strictdoc.features.project_statistics.view_object import (
    ProjectStatisticsViewObject,
)


TRACKED_NODE_TYPES = {
    "REQUIREMENT",
    "DESIGN",
    "IMPLEMENTATION",
    "MILESTONE",
    "SAFETY",
    "SECURITY",
}

PLACEHOLDER_MARKERS = (
    "replace with",
    "not yet evaluated",
    "tbd",
    "tbc",
    "todo",
)


def _value_to_text(value: object) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, (list, tuple, set)):
        return ", ".join(_value_to_text(item) for item in value)

    for method_name in ("get_text_value", "get_value"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                method_value = method()
            except (AttributeError, TypeError):
                continue

            if method_value is not value:
                return _value_to_text(method_value)

    for attribute_name in ("field_value", "value"):
        if not hasattr(value, attribute_name):
            continue

        attribute_value = getattr(value, attribute_name)
        if attribute_value is not value:
            return _value_to_text(attribute_value)

    return str(value)


def _field_value(node: SDocNode, field_name: str) -> Optional[str]:
    field = node.ordered_fields_lookup.get(field_name)
    if field is None:
        return None

    value = _value_to_text(field).strip()
    return value if value else None


def _field_equals_link(field_name: str, value: str) -> str:
    escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
    query = f'node["{field_name}"] == "{escaped_value}"'
    return f"search?q={quote(query)}"


def _contains_template_tag(node: SDocNode) -> bool:
    tags = _field_value(node, "TAGS")
    if tags is None:
        return False

    normalized_tags = {
        tag.strip().lower()
        for tag in tags.replace(";", ",").split(",")
        if tag.strip()
    }
    return "template" in normalized_tags


def _node_text(node: SDocNode) -> str:
    values = (
        _value_to_text(field)
        for field in node.ordered_fields_lookup.values()
    )
    return "\n".join(value for value in values if value)


def _has_placeholder(node: SDocNode) -> bool:
    normalized_text = _node_text(node).lower()
    return any(marker in normalized_text for marker in PLACEHOLDER_MARKERS)


def _field_missing_or_placeholder(
    node: SDocNode,
    field_name: str,
) -> bool:
    value = _field_value(node, field_name)
    if value is None:
        return True

    normalized_value = value.lower()
    return any(
        marker in normalized_value
        for marker in PLACEHOLDER_MARKERS
    )


def _parents(
    traceability_index: TraceabilityIndex,
    node: SDocNode,
) -> list[SDocNode]:
    try:
        return list(traceability_index.get_parent_requirements(node))
    except (AssertionError, AttributeError, KeyError, TypeError):
        return []


def _children(
    traceability_index: TraceabilityIndex,
    node: SDocNode,
) -> list[SDocNode]:
    try:
        return list(traceability_index.get_children_requirements(node))
    except (AssertionError, AttributeError, KeyError, TypeError):
        return []


def _has_relation_to_type(
    traceability_index: TraceabilityIndex,
    node: SDocNode,
    node_types: set[str],
) -> bool:
    related_nodes = [
        *_parents(traceability_index, node),
        *_children(traceability_index, node),
    ]
    return any(
        related_node.node_type in node_types
        for related_node in related_nodes
    )


def _has_relation_to_field_value(
    traceability_index: TraceabilityIndex,
    node: SDocNode,
    field_name: str,
    expected_values: set[str],
) -> bool:
    related_nodes = [
        *_parents(traceability_index, node),
        *_children(traceability_index, node),
    ]
    return any(
        _field_value(related_node, field_name) in expected_values
        for related_node in related_nodes
    )


def _count_by_field(
    nodes: Iterable[SDocNode],
    field_name: str,
) -> Counter[str]:
    values: Counter[str] = Counter()
    for node in nodes:
        value = _field_value(node, field_name)
        values[value if value is not None else "Not set"] += 1
    return values


def _breakdown_metrics(
    *,
    nodes: Iterable[SDocNode],
    field_name: str,
    label: str,
) -> list[Metric]:
    breakdown = _count_by_field(nodes, field_name)
    return [
        Metric(
            name=f"{label}: {value}",
            value=str(count),
            link=(
                None
                if value == "Not set"
                else _field_equals_link(field_name, value)
            ),
        )
        for value, count in sorted(
            breakdown.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def _section(name: str, metrics: list[Metric]) -> MetricSection:
    return MetricSection(name=name, metrics=metrics)


class DocumentationStatisticsGenerator:
    """Generate lifecycle, traceability, and assurance health statistics."""

    @staticmethod
    def export(
        project_config: ProjectConfig,
        traceability_index: TraceabilityIndex,
        link_renderer: LinkRenderer,
        html_templates: HTMLTemplates,
    ) -> Markup:
        all_nodes: list[SDocNode] = []

        for document in traceability_index.document_tree.document_list:
            document_iterator = SDocDocumentIterator(document)
            for node, _ in document_iterator.all_content(
                print_fragments=False
            ):
                if (
                    isinstance(node, SDocNode)
                    and node.node_type in TRACKED_NODE_TYPES
                ):
                    all_nodes.append(node)

        template_nodes = [
            node for node in all_nodes if _contains_template_tag(node)
        ]
        project_nodes = [
            node for node in all_nodes if not _contains_template_tag(node)
        ]

        requirements = [
            node for node in project_nodes
            if node.node_type == "REQUIREMENT"
        ]
        designs = [
            node for node in project_nodes
            if node.node_type == "DESIGN"
        ]
        implementation = [
            node for node in project_nodes
            if node.node_type == "IMPLEMENTATION"
        ]
        milestones = [
            node for node in project_nodes
            if node.node_type == "MILESTONE"
        ]
        safety = [
            node for node in project_nodes
            if node.node_type == "SAFETY"
        ]
        security = [
            node for node in project_nodes
            if node.node_type == "SECURITY"
        ]

        all_requirements = [
            node for node in all_nodes
            if node.node_type == "REQUIREMENT"
        ]
        all_designs = [
            node for node in all_nodes
            if node.node_type == "DESIGN"
        ]
        all_implementation = [
            node for node in all_nodes
            if node.node_type == "IMPLEMENTATION"
        ]
        all_milestones = [
            node for node in all_nodes
            if node.node_type == "MILESTONE"
        ]
        all_safety = [
            node for node in all_nodes
            if node.node_type == "SAFETY"
        ]
        all_security = [
            node for node in all_nodes
            if node.node_type == "SECURITY"
        ]

        metrics: list[Metric | MetricSection] = []

        metrics.append(
            _section(
                "Project overview",
                [
                    Metric(
                        name="Documents",
                        value=str(
                            len(
                                traceability_index
                                .document_tree
                                .document_list
                            )
                        ),
                    ),
                    Metric(
                        name="Traceable records",
                        value=str(len(all_nodes)),
                    ),
                    Metric(
                        name="Template example records",
                        value=str(len(template_nodes)),
                    ),
                    Metric(
                        name="Project records",
                        value=str(len(project_nodes)),
                    ),
                    Metric(
                        name="Project records containing placeholders",
                        value=str(
                            sum(
                                1
                                for node in project_nodes
                                if _has_placeholder(node)
                            )
                        ),
                    ),
                    Metric(
                        name="Template records containing placeholders",
                        value=str(
                            sum(
                                1
                                for node in template_nodes
                                if _has_placeholder(node)
                            )
                        ),
                    ),
                ],
            )
        )

        metrics.append(
            _section(
                "Artifact inventory",
                [
                    Metric(
                        name="Requirements",
                        value=str(len(all_requirements)),
                    ),
                    Metric(
                        name="Design records",
                        value=str(len(all_designs)),
                    ),
                    Metric(
                        name="Implementation and verification records",
                        value=str(len(all_implementation)),
                    ),
                    Metric(
                        name="Milestones",
                        value=str(len(all_milestones)),
                    ),
                    Metric(
                        name="Safety-assurance records",
                        value=str(len(all_safety)),
                    ),
                    Metric(
                        name="Security-assurance records",
                        value=str(len(all_security)),
                    ),
                ],
            )
        )

        requirement_metrics = [
            Metric(
                name="Project requirements",
                value=str(len(requirements)),
            ),
            Metric(
                name="Requirements without rationale",
                value=str(
                    sum(
                        1
                        for node in requirements
                        if _field_value(node, "RATIONALE") is None
                    )
                ),
            ),
            Metric(
                name="Requirements without acceptance criteria",
                value=str(
                    sum(
                        1
                        for node in requirements
                        if _field_value(node, "ACCEPTANCE") is None
                    )
                ),
            ),
        ]
        requirement_metrics.extend(
            _breakdown_metrics(
                nodes=requirements,
                field_name="STATUS",
                label="Status",
            )
        )
        requirement_metrics.extend(
            _breakdown_metrics(
                nodes=requirements,
                field_name="CATEGORY",
                label="Category",
            )
        )
        requirement_metrics.extend(
            _breakdown_metrics(
                nodes=requirements,
                field_name="PRIORITY",
                label="Priority",
            )
        )
        requirement_metrics.extend(
            _breakdown_metrics(
                nodes=requirements,
                field_name="SAFETY_CLASS",
                label="Safety class",
            )
        )
        metrics.append(_section("Requirements", requirement_metrics))

        design_metrics = [
            Metric(
                name="Project design records",
                value=str(len(designs)),
            ),
            Metric(
                name="Safety-critical designs without deep design",
                value=str(
                    sum(
                        1
                        for node in designs
                        if (
                            _field_value(
                                node,
                                "SAFETY_RELEVANCE",
                            )
                            == "SafetyCritical"
                            and _field_value(
                                node,
                                "DESIGN_DEPTH",
                            )
                            != "Deep"
                        )
                    )
                ),
            ),
            Metric(
                name="Interface designs without an interface contract",
                value=str(
                    sum(
                        1
                        for node in designs
                        if (
                            _field_value(node, "DESIGN_TYPE")
                            == "Interface"
                            and _field_value(
                                node,
                                "INTERFACE_CONTRACT",
                            )
                            is None
                        )
                    )
                ),
            ),
        ]
        design_metrics.extend(
            _breakdown_metrics(
                nodes=designs,
                field_name="STATUS",
                label="Status",
            )
        )
        design_metrics.extend(
            _breakdown_metrics(
                nodes=designs,
                field_name="DESIGN_TYPE",
                label="Design type",
            )
        )
        design_metrics.extend(
            _breakdown_metrics(
                nodes=designs,
                field_name="DESIGN_DEPTH",
                label="Design depth",
            )
        )
        design_metrics.extend(
            _breakdown_metrics(
                nodes=designs,
                field_name="SAFETY_RELEVANCE",
                label="Safety relevance",
            )
        )
        metrics.append(_section("Design", design_metrics))

        completed_verification = [
            node for node in implementation
            if (
                _field_value(node, "TYPE")
                in {"Verification", "Validation"}
                and _field_value(node, "STATUS") == "Complete"
            )
        ]
        implementation_metrics = [
            Metric(
                name="Project implementation and verification records",
                value=str(len(implementation)),
            ),
            Metric(
                name="Failed verification or validation records",
                value=str(
                    sum(
                        1
                        for node in implementation
                        if (
                            _field_value(node, "TYPE")
                            in {"Verification", "Validation"}
                            and _field_value(node, "RESULT") == "Failed"
                        )
                    )
                ),
                link=_field_equals_link("RESULT", "Failed"),
            ),
            Metric(
                name="Blocked verification or validation records",
                value=str(
                    sum(
                        1
                        for node in implementation
                        if (
                            _field_value(node, "TYPE")
                            in {"Verification", "Validation"}
                            and (
                                _field_value(node, "RESULT") == "Blocked"
                                or _field_value(node, "STATUS") == "Blocked"
                            )
                        )
                    )
                ),
            ),
            Metric(
                name="Completed verification without a baseline",
                value=str(
                    sum(
                        1
                        for node in completed_verification
                        if _field_value(node, "BASELINE") is None
                    )
                ),
            ),
            Metric(
                name="Completed verification without evidence",
                value=str(
                    sum(
                        1
                        for node in completed_verification
                        if _field_value(node, "EVIDENCE") is None
                    )
                ),
            ),
            Metric(
                name="Completed verification without reviewer metadata",
                value=str(
                    sum(
                        1
                        for node in completed_verification
                        if (
                            _field_value(node, "REVIEWER") is None
                            or _field_value(node, "REVIEW_DATE") is None
                        )
                    )
                ),
            ),
            Metric(
                name="Safety-critical verification without independent review",
                value=str(
                    sum(
                        1
                        for node in implementation
                        if (
                            _field_value(node, "TYPE")
                            in {"Verification", "Validation"}
                            and _field_value(
                                node,
                                "SAFETY_RELEVANCE",
                            )
                            == "SafetyCritical"
                            and _field_value(node, "INDEPENDENCE")
                            not in {
                                "IndependentPerson",
                                "IndependentOrganization",
                                "ExternalAssessor",
                            }
                        )
                    )
                ),
            ),
        ]
        implementation_metrics.extend(
            _breakdown_metrics(
                nodes=implementation,
                field_name="STATUS",
                label="Status",
            )
        )
        implementation_metrics.extend(
            _breakdown_metrics(
                nodes=implementation,
                field_name="TYPE",
                label="Record type",
            )
        )
        implementation_metrics.extend(
            _breakdown_metrics(
                nodes=implementation,
                field_name="RESULT",
                label="Result",
            )
        )
        implementation_metrics.extend(
            _breakdown_metrics(
                nodes=implementation,
                field_name="SAFETY_RELEVANCE",
                label="Safety relevance",
            )
        )
        metrics.append(
            _section(
                "Implementation and verification",
                implementation_metrics,
            )
        )

        completed_milestones = [
            node for node in milestones
            if _field_value(node, "STATUS") == "Complete"
        ]
        milestone_metrics = [
            Metric(
                name="Project milestones",
                value=str(len(milestones)),
            ),
            Metric(
                name="At-risk milestones",
                value=str(
                    sum(
                        1
                        for node in milestones
                        if _field_value(node, "STATUS") == "AtRisk"
                    )
                ),
                link=_field_equals_link("STATUS", "AtRisk"),
            ),
            Metric(
                name="Completed milestones without approval",
                value=str(
                    sum(
                        1
                        for node in completed_milestones
                        if _field_value(node, "APPROVAL") is None
                    )
                ),
            ),
            Metric(
                name="Completed milestones with placeholder baselines",
                value=str(
                    sum(
                        1
                        for node in completed_milestones
                        if (
                            _field_value(node, "BASELINE") is None
                            or "replace with" in (
                                _field_value(node, "BASELINE") or ""
                            ).lower()
                        )
                    )
                ),
            ),
        ]
        milestone_metrics.extend(
            _breakdown_metrics(
                nodes=milestones,
                field_name="STATUS",
                label="Status",
            )
        )
        milestone_metrics.extend(
            _breakdown_metrics(
                nodes=milestones,
                field_name="GATE_TYPE",
                label="Gate type",
            )
        )
        milestone_metrics.extend(
            _breakdown_metrics(
                nodes=milestones,
                field_name="SAFETY_RELEVANCE",
                label="Safety relevance",
            )
        )
        metrics.append(_section("Milestones", milestone_metrics))

        hazards = [
            node for node in safety
            if _field_value(node, "TYPE") == "Hazard"
        ]
        risk_controls = [
            node for node in safety
            if _field_value(node, "TYPE") == "RiskControl"
        ]
        safety_functions = [
            node for node in safety
            if _field_value(node, "TYPE") == "SafetyFunction"
        ]
        compliance_obligations = [
            node for node in safety
            if _field_value(node, "TYPE") == "ComplianceObligation"
        ]
        assurance_claims = [
            node for node in safety
            if _field_value(node, "TYPE") == "AssuranceClaim"
        ]

        safety_metrics = [
            Metric(
                name="Project safety-assurance records",
                value=str(len(safety)),
            ),
            Metric(
                name="Hazards without an initial-risk evaluation",
                value=str(
                    sum(
                        1
                        for node in hazards
                        if (
                            _field_value(node, "INITIAL_RISK") is None
                            or _has_placeholder(node)
                        )
                    )
                ),
            ),
            Metric(
                name="Hazards without a residual-risk evaluation",
                value=str(
                    sum(
                        1
                        for node in hazards
                        if (
                            _field_value(node, "RESIDUAL_RISK") is None
                            or "not yet evaluated" in (
                                _field_value(node, "RESIDUAL_RISK")
                                or ""
                            ).lower()
                        )
                    )
                ),
            ),
            Metric(
                name="Risk controls without a reduction category",
                value=str(
                    sum(
                        1
                        for node in risk_controls
                        if (
                            _field_value(
                                node,
                                "RISK_REDUCTION_TYPE",
                            )
                            is None
                        )
                    )
                ),
            ),
            Metric(
                name="Safety functions without an integrity target",
                value=str(
                    sum(
                        1
                        for node in safety_functions
                        if (
                            _field_value(node, "INTEGRITY_TARGET")
                            is None
                        )
                    )
                ),
            ),
            Metric(
                name="Safety functions without a safe state",
                value=str(
                    sum(
                        1
                        for node in safety_functions
                        if _field_value(node, "SAFE_STATE") is None
                    )
                ),
            ),
            Metric(
                name="Safety functions without a response time",
                value=str(
                    sum(
                        1
                        for node in safety_functions
                        if _field_value(node, "RESPONSE_TIME") is None
                    )
                ),
            ),
            Metric(
                name="Safety functions without fault-reaction behavior",
                value=str(
                    sum(
                        1
                        for node in safety_functions
                        if _field_value(node, "FAULT_REACTION") is None
                    )
                ),
            ),
            Metric(
                name="Candidate compliance obligations",
                value=str(
                    sum(
                        1
                        for node in compliance_obligations
                        if (
                            _field_value(node, "APPLICABILITY")
                            == "Candidate"
                        )
                    )
                ),
                link=_field_equals_link("APPLICABILITY", "Candidate"),
            ),
            Metric(
                name="Accepted assurance claims",
                value=str(
                    sum(
                        1
                        for node in assurance_claims
                        if _field_value(node, "STATUS") == "Accepted"
                    )
                ),
            ),
        ]
        safety_metrics.extend(
            _breakdown_metrics(
                nodes=safety,
                field_name="TYPE",
                label="Record type",
            )
        )
        safety_metrics.extend(
            _breakdown_metrics(
                nodes=safety,
                field_name="STATUS",
                label="Status",
            )
        )
        metrics.append(_section("Safety assurance", safety_metrics))

        security_threats = [
            node for node in security
            if _field_value(node, "TYPE") == "Threat"
        ]
        security_controls = [
            node for node in security
            if _field_value(node, "TYPE") == "SecurityControl"
        ]
        vulnerability_management_records = [
            node for node in security
            if _field_value(node, "TYPE") == "VulnerabilityManagement"
        ]
        incident_response_records = [
            node for node in security
            if _field_value(node, "TYPE") == "IncidentResponse"
        ]
        security_compliance_obligations = [
            node for node in security
            if _field_value(node, "TYPE") == "ComplianceObligation"
        ]
        security_assurance_claims = [
            node for node in security
            if _field_value(node, "TYPE") == "AssuranceClaim"
        ]

        security_metrics = [
            Metric(
                name="Project security-assurance records",
                value=str(len(security)),
            ),
            Metric(
                name="Threats without an initial-risk evaluation",
                value=str(
                    sum(
                        1
                        for node in security_threats
                        if _field_missing_or_placeholder(
                            node,
                            "INITIAL_RISK",
                        )
                    )
                ),
            ),
            Metric(
                name="Threats without a residual-risk evaluation",
                value=str(
                    sum(
                        1
                        for node in security_threats
                        if _field_missing_or_placeholder(
                            node,
                            "RESIDUAL_RISK",
                        )
                    )
                ),
            ),
            Metric(
                name="Threats without documented safety impact",
                value=str(
                    sum(
                        1
                        for node in security_threats
                        if _field_value(node, "SAFETY_IMPACT") is None
                    )
                ),
            ),
            Metric(
                name="Security controls without a control type",
                value=str(
                    sum(
                        1
                        for node in security_controls
                        if _field_value(node, "CONTROL_TYPE") is None
                    )
                ),
            ),
            Metric(
                name="Security controls without security objectives",
                value=str(
                    sum(
                        1
                        for node in security_controls
                        if _field_value(node, "SECURITY_OBJECTIVES") is None
                    )
                ),
            ),
            Metric(
                name="Security controls without verification methods",
                value=str(
                    sum(
                        1
                        for node in security_controls
                        if _field_value(node, "VERIFICATION_METHOD") is None
                    )
                ),
            ),
            Metric(
                name="Security controls without residual-risk evaluation",
                value=str(
                    sum(
                        1
                        for node in security_controls
                        if _field_missing_or_placeholder(
                            node,
                            "RESIDUAL_RISK",
                        )
                    )
                ),
            ),
            Metric(
                name="Vulnerability-management records",
                value=str(len(vulnerability_management_records)),
            ),
            Metric(
                name="Incident-response records",
                value=str(len(incident_response_records)),
            ),
            Metric(
                name="Candidate security compliance obligations",
                value=str(
                    sum(
                        1
                        for node in security_compliance_obligations
                        if (
                            _field_value(node, "APPLICABILITY")
                            == "Candidate"
                        )
                    )
                ),
                link=_field_equals_link("APPLICABILITY", "Candidate"),
            ),
            Metric(
                name="Accepted security assurance claims",
                value=str(
                    sum(
                        1
                        for node in security_assurance_claims
                        if _field_value(node, "STATUS") == "Accepted"
                    )
                ),
            ),
        ]
        security_metrics.extend(
            _breakdown_metrics(
                nodes=security,
                field_name="TYPE",
                label="Record type",
            )
        )
        security_metrics.extend(
            _breakdown_metrics(
                nodes=security,
                field_name="STATUS",
                label="Status",
            )
        )
        security_metrics.extend(
            _breakdown_metrics(
                nodes=security_controls,
                field_name="CONTROL_TYPE",
                label="Control type",
            )
        )
        metrics.append(
            _section(
                "Security assurance",
                security_metrics,
            )
        )

        requirement_traceability_gaps = sum(
            1
            for node in requirements
            if (
                _field_value(node, "CATEGORY") != "UserStory"
                and not _parents(traceability_index, node)
            )
        )
        safety_requirement_traceability_gaps = sum(
            1
            for node in requirements
            if (
                _field_value(node, "CATEGORY") == "Safety"
                and not _has_relation_to_field_value(
                    traceability_index,
                    node,
                    "TYPE",
                    {"RiskControl", "SafetyFunction"},
                )
            )
        )
        design_traceability_gaps = sum(
            1
            for node in designs
            if not _parents(traceability_index, node)
        )
        implementation_traceability_gaps = sum(
            1
            for node in implementation
            if not _has_relation_to_type(
                traceability_index,
                node,
                {
                    "REQUIREMENT",
                    "DESIGN",
                    "IMPLEMENTATION",
                    "SAFETY",
                    "SECURITY",
                },
            )
        )
        hazard_control_gaps = sum(
            1
            for node in hazards
            if not _has_relation_to_field_value(
                traceability_index,
                node,
                "TYPE",
                {"RiskControl"},
            )
        )
        safety_function_evidence_gaps = sum(
            1
            for node in safety_functions
            if not _has_relation_to_type(
                traceability_index,
                node,
                {
                    "REQUIREMENT",
                    "DESIGN",
                    "IMPLEMENTATION",
                    "SECURITY",
                },
            )
        )
        milestone_traceability_gaps = sum(
            1
            for node in milestones
            if not _parents(traceability_index, node)
        )
        assurance_claim_support_gaps = sum(
            1
            for node in assurance_claims
            if not _has_relation_to_type(
                traceability_index,
                node,
                {"IMPLEMENTATION", "MILESTONE", "SECURITY"},
            )
        )
        security_threat_control_gaps = sum(
            1
            for node in security_threats
            if not _has_relation_to_field_value(
                traceability_index,
                node,
                "TYPE",
                {"SecurityControl"},
            )
        )
        security_control_evidence_gaps = sum(
            1
            for node in security_controls
            if not _has_relation_to_type(
                traceability_index,
                node,
                {"REQUIREMENT", "DESIGN", "IMPLEMENTATION"},
            )
        )
        security_safety_traceability_gaps = sum(
            1
            for node in security
            if (
                _field_value(node, "SAFETY_IMPACT") is not None
                and not _has_relation_to_type(
                    traceability_index,
                    node,
                    {"REQUIREMENT", "DESIGN", "SAFETY"},
                )
            )
        )
        security_claim_support_gaps = sum(
            1
            for node in security_assurance_claims
            if not _has_relation_to_type(
                traceability_index,
                node,
                {"IMPLEMENTATION", "MILESTONE"},
            )
        )

        metrics.append(
            _section(
                "Project traceability",
                [
                    Metric(
                        name="Non-root requirements without parents",
                        value=str(requirement_traceability_gaps),
                    ),
                    Metric(
                        name=(
                            "Safety requirements without a risk-control "
                            "or safety-function relation"
                        ),
                        value=str(safety_requirement_traceability_gaps),
                    ),
                    Metric(
                        name="Design records without parents",
                        value=str(design_traceability_gaps),
                    ),
                    Metric(
                        name=(
                            "Implementation records without lifecycle "
                            "relations"
                        ),
                        value=str(implementation_traceability_gaps),
                    ),
                    Metric(
                        name="Hazards without related risk controls",
                        value=str(hazard_control_gaps),
                    ),
                    Metric(
                        name=(
                            "Safety functions without implementation "
                            "or verification support"
                        ),
                        value=str(safety_function_evidence_gaps),
                    ),
                    Metric(
                        name="Milestones without included records",
                        value=str(milestone_traceability_gaps),
                    ),
                    Metric(
                        name=(
                            "Safety assurance claims without evidence "
                            "or milestone support"
                        ),
                        value=str(assurance_claim_support_gaps),
                    ),
                    Metric(
                        name="Security threats without related controls",
                        value=str(security_threat_control_gaps),
                    ),
                    Metric(
                        name=(
                            "Security controls without implementation "
                            "or verification support"
                        ),
                        value=str(security_control_evidence_gaps),
                    ),
                    Metric(
                        name=(
                            "Security records with safety impact but "
                            "without safety traceability"
                        ),
                        value=str(security_safety_traceability_gaps),
                    ),
                    Metric(
                        name=(
                            "Security assurance claims without evidence "
                            "or milestone support"
                        ),
                        value=str(security_claim_support_gaps),
                    ),
                ],
            )
        )

        metrics.append(
            _section(
                "Authoring debt",
                [
                    Metric(
                        name="Project records containing TBD",
                        value=str(
                            sum(
                                1
                                for node in project_nodes
                                if "tbd" in _node_text(node).lower()
                            )
                        ),
                        link="search?q=TBD",
                    ),
                    Metric(
                        name="Project records containing TBC",
                        value=str(
                            sum(
                                1
                                for node in project_nodes
                                if "tbc" in _node_text(node).lower()
                            )
                        ),
                        link="search?q=TBC",
                    ),
                    Metric(
                        name="Project records containing TODO",
                        value=str(
                            sum(
                                1
                                for node in project_nodes
                                if "todo" in _node_text(node).lower()
                            )
                        ),
                        link="search?q=TODO",
                    ),
                    Metric(
                        name="Project records containing replacement text",
                        value=str(
                            sum(
                                1
                                for node in project_nodes
                                if (
                                    "replace with"
                                    in _node_text(node).lower()
                                )
                            )
                        ),
                        link=f"search?q={quote('Replace with')}",
                    ),
                    Metric(
                        name="Project records without a UID",
                        value=str(
                            sum(
                                1
                                for node in project_nodes
                                if _field_value(node, "UID") is None
                            )
                        ),
                    ),
                ],
            )
        )

        view_object = ProjectStatisticsViewObject(
            traceability_index=traceability_index,
            project_config=project_config,
            link_renderer=link_renderer,
            metrics=metrics,
        )
        return view_object.render_screen(
            html_templates.jinja_environment()
        )
