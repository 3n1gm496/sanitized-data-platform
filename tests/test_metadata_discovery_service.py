from sanitized_data_platform.application.services import MetadataDiscoveryService
from sanitized_data_platform.domain.entities import MetadataObject
from sanitized_data_platform.domain.enums import MetadataObjectType

from tests.fakes import InMemoryDataSourceRepository, sample_source


class StubMetadataDiscoveryAdapter:
    def list_schemas(self, source):
        return [
            MetadataObject(
                object_id="schema:source-crm-replica:public",
                source_id=source.source_id,
                system_id=source.system_id,
                system_name=source.system_name,
                object_type=MetadataObjectType.SCHEMA,
                name="public",
                qualified_name="public",
            )
        ]

    def list_tables(self, source):
        return [
            MetadataObject(
                object_id="table:source-crm-replica:public.customers",
                source_id=source.source_id,
                system_id=source.system_id,
                system_name=source.system_name,
                object_type=MetadataObjectType.TABLE,
                name="customers",
                qualified_name="public.customers",
                container_name="public",
                parent_object_id="schema:source-crm-replica:public",
            )
        ]

    def list_columns(self, source):
        return [
            MetadataObject(
                object_id="column:source-crm-replica:public.customers.email",
                source_id=source.source_id,
                system_id=source.system_id,
                system_name=source.system_name,
                object_type=MetadataObjectType.COLUMN,
                name="email",
                qualified_name="public.customers.email",
                container_name="public.customers",
                parent_object_id="table:source-crm-replica:public.customers",
                logical_data_type="string",
            )
        ]

    def list_relationships(self, source):
        return []


def test_metadata_discovery_service_builds_catalog_view_from_adapter():
    service = MetadataDiscoveryService(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        discovery=StubMetadataDiscoveryAdapter(),
    )

    result = service.discover_metadata_objects("source-crm-replica")

    assert result.source_id == "source-crm-replica"
    assert result.system_id == "crm"
    assert [item.object_type for item in result.items] == ["schema", "table", "column"]
    assert result.items[2].logical_data_type == "string"
