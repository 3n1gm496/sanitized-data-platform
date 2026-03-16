"""PostgreSQL-specific adapters."""

from .extraction_pipeline import PostgreSQLExtractionPipelineAdapter
from .metadata_discovery import PostgreSQLMetadataDiscoveryAdapter

__all__ = [
    "PostgreSQLExtractionPipelineAdapter",
    "PostgreSQLMetadataDiscoveryAdapter",
]
