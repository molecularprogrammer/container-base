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
        ],
        statistics_generator=(
            "docs.sdoc_project_statistics.DocumentationStatisticsGenerator"
        ),
        # source_root_path="source_root/",
    )
    return config
