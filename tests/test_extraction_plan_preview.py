from sanitized_data_platform.application.dto import PreviewExtractionPlanCommand
from sanitized_data_platform.application.services import (
    ExtractionPlanPreviewService,
    ExtractionPlanningService,
)
from sanitized_data_platform.domain.entities import MetadataObject, Relationship
from sanitized_data_platform.domain.enums import MetadataObjectType

from tests.fakes import InMemoryMetadataCatalogRepository, sample_source


def preview_metadata_objects() -> list[MetadataObject]:
    source = sample_source()
    return [
        MetadataObject(
            object_id="table-customers",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="customers",
            qualified_name="crm.customers",
        ),
        MetadataObject(
            object_id="table-orders",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.TABLE,
            name="orders",
            qualified_name="crm.orders",
        ),
        MetadataObject(
            object_id="column-customers-customer-id",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="customer_id",
            qualified_name="crm.customers.customer_id",
            container_name="crm.customers",
            parent_object_id="table-customers",
            logical_data_type="integer",
        ),
        MetadataObject(
            object_id="column-orders-customer-id",
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            object_type=MetadataObjectType.COLUMN,
            name="customer_id",
            qualified_name="crm.orders.customer_id",
            container_name="crm.orders",
            parent_object_id="table-orders",
            logical_data_type="integer",
        ),
    ]


def preview_relationships() -> list[Relationship]:
    source = sample_source()
    return [
        Relationship(
            relationship_id="fk:orders.customer_id->customers.customer_id",
            source_id=source.source_id,
            source_object_id="column-orders-customer-id",
            target_object_id="column-customers-customer-id",
            relationship_type="foreign_key",
            inferred=False,
            confidence=1.0,
        )
    ]


def build_preview_service(*, relationships: list[Relationship] | None = None):
    return ExtractionPlanPreviewService(
        ExtractionPlanningService(
            InMemoryMetadataCatalogRepository(
                preview_metadata_objects(),
                preview_relationships() if relationships is None else relationships,
            )
        )
    )


def test_extraction_plan_preview_returns_root_only_plan():
    service = build_preview_service()

    result = service.preview_plan(
        PreviewExtractionPlanCommand(
            source_id="source-crm-replica",
            root_object_id="table-customers",
            criteria=[{"fieldName": "customer_id", "operator": "eq", "value": "42"}],
            include_related=False,
            max_depth=1,
        )
    )

    assert result.root_object_id == "table-customers"
    assert result.criteria[0].field_name == "customer_id"
    assert result.artifact_kind == "sample"
    assert result.selected_object_ids == ["table-customers"]
    assert result.selected_relationship_ids == []


def test_extraction_plan_preview_returns_selected_columns_for_root():
    service = build_preview_service()

    result = service.preview_plan(
        PreviewExtractionPlanCommand(
            source_id="source-crm-replica",
            root_object_id="table-customers",
            criteria=[],
            selected_columns=["customer_id"],
            include_related=False,
            max_depth=1,
        )
    )

    assert result.root_object_id == "table-customers"
    assert result.artifact_kind == "sample"
    assert result.selected_columns == ["customer_id"]
    assert result.selected_object_ids == ["table-customers"]


def test_extraction_plan_preview_can_request_full_artifact_kind():
    service = build_preview_service()

    result = service.preview_plan(
        PreviewExtractionPlanCommand(
            source_id="source-crm-replica",
            root_object_id="table-customers",
            criteria=[],
            artifact_kind="full",
            include_related=False,
            max_depth=1,
        )
    )

    assert result.root_object_id == "table-customers"
    assert result.artifact_kind == "full"


def test_extraction_plan_preview_returns_fk_expanded_plan():
    service = build_preview_service()

    result = service.preview_plan(
        PreviewExtractionPlanCommand(
            source_id="source-crm-replica",
            root_object_id="table-customers",
            criteria=[],
            include_related=True,
            max_depth=1,
        )
    )

    assert result.include_related is True
    assert set(result.selected_object_ids) == {"table-customers", "table-orders"}
    assert result.selected_relationship_ids == [
        "fk:orders.customer_id->customers.customer_id"
    ]


def test_extraction_plan_preview_reports_absent_relationships():
    service = build_preview_service(relationships=[])

    result = service.preview_plan(
        PreviewExtractionPlanCommand(
            source_id="source-crm-replica",
            root_object_id="table-customers",
            criteria=[],
            include_related=True,
            max_depth=1,
        )
    )

    assert result.selected_object_ids == ["table-customers"]
    assert result.selected_relationship_ids == []
    assert result.notes == [
        "No active foreign-key relationships expanded from the selected root."
    ]
