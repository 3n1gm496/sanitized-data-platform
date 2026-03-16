from dataclasses import replace

from sanitized_data_platform.application.services import (
    MetadataIngestionService,
    MetadataQueryService,
)

from tests.fakes import (
    InMemoryDataSourceRepository,
    InMemoryMetadataCatalogRepository,
    InMemorySystemRepository,
    sample_metadata_objects,
    sample_source,
    sample_system,
)


class StubMetadataDiscoveryAdapter:
    def __init__(self, objects):
        self._objects = list(objects)

    def list_schemas(self, source):
        return [item for item in self._objects if item.object_type.value == "schema"]

    def list_tables(self, source):
        return [item for item in self._objects if item.object_type.value == "table"]

    def list_columns(self, source):
        return [item for item in self._objects if item.object_type.value == "column"]

    def list_relationships(self, source):
        return []


def test_metadata_ingestion_persists_discovered_objects_into_catalog():
    catalog = InMemoryMetadataCatalogRepository(objects=[])
    service = MetadataIngestionService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        discovery=StubMetadataDiscoveryAdapter(sample_metadata_objects()),
        metadata_catalog=catalog,
    )

    result = service.ingest_discovered_metadata("source-crm-replica")

    assert result.source_id == "source-crm-replica"
    assert len(result.items) == 3
    assert [item.qualified_name for item in result.items] == [
        "crm.customers",
        "crm.customers.email",
        "crm.customers.status",
    ]
    assert service.list_ingested_relationships("source-crm-replica") == []


def test_metadata_ingestion_is_idempotent_for_repeated_discovery():
    catalog = InMemoryMetadataCatalogRepository(objects=[])
    service = MetadataIngestionService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        discovery=StubMetadataDiscoveryAdapter(sample_metadata_objects()),
        metadata_catalog=catalog,
    )

    first = service.ingest_discovered_metadata("source-crm-replica")
    second = service.ingest_discovered_metadata("source-crm-replica")

    assert len(first.items) == 3
    assert len(second.items) == 3
    assert len(catalog.list_objects("source-crm-replica")) == 3


def test_metadata_ingestion_updates_existing_metadata_objects():
    updated_objects = sample_metadata_objects()
    updated_objects[1] = replace(
        updated_objects[1],
        logical_data_type="large_text",
    )
    catalog = InMemoryMetadataCatalogRepository(objects=sample_metadata_objects())
    ingestion = MetadataIngestionService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        discovery=StubMetadataDiscoveryAdapter(updated_objects),
        metadata_catalog=catalog,
    )
    queries = MetadataQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        metadata_catalog=catalog,
    )

    ingestion.ingest_discovered_metadata("source-crm-replica")
    result = queries.list_metadata_objects("crm")

    email_column = next(item for item in result.items if item.name == "email")
    assert email_column.logical_data_type == "large_text"


def test_metadata_ingestion_upserts_relationships_without_duplicates():
    from sanitized_data_platform.domain.entities import Relationship

    relationship = Relationship(
        relationship_id="pk:source-crm-replica:crm.customers.customer_id",
        source_id="source-crm-replica",
        source_object_id="table:source-crm-replica:crm.customers",
        target_object_id="column:source-crm-replica:crm.customers.customer_id",
        relationship_type="primary_key",
        inferred=False,
        confidence=1.0,
    )

    class RelationshipDiscoveryAdapter(StubMetadataDiscoveryAdapter):
        def list_relationships(self, source):
            return [relationship]

    catalog = InMemoryMetadataCatalogRepository(objects=[])
    service = MetadataIngestionService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        discovery=RelationshipDiscoveryAdapter(sample_metadata_objects()),
        metadata_catalog=catalog,
    )

    service.ingest_discovered_metadata("source-crm-replica")
    service.ingest_discovered_metadata("source-crm-replica")

    relationships = service.list_ingested_relationships("source-crm-replica")
    assert len(relationships) == 1
    assert relationships[0].relationship_type == "primary_key"
