from strictdoc.core.project_config import ProjectConfig


def create_config() -> ProjectConfig:
    config = ProjectConfig(
        project_title="Documentation Project Template",
        document_line_width=100,
        project_features=[
            "TABLE_SCREEN",
            "TRACEABILITY_SCREEN",
            "DEEP_TRACEABILITY_SCREEN",
            "SEARCH",
            "PROJECT_STATISTICS_SCREEN",
            "TRACEABILITY_MATRIX_SCREEN",
            "REQUIREMENT_TO_SOURCE_TRACEABILITY",
        ],
        include_doc_paths=[
            "/docs/**",
            "/grammar/**"
        ],
        grammars={
            "@requirements": "grammar/requirements.sgra",
            "@design": "grammar/design.sgra",
            "@implementation": "grammar/implementation.sgra",
            "@milestones": "grammar/milestones.sgra",
            "@safety": "grammar/safety.sgra",
            "@security": "grammar/security.sgra",
        },
        statistics_generator=(
            "sdoc_project_statistics.DocumentationStatisticsGenerator"
        ),
        # source_root_path="source_root/",
    )
    return config
