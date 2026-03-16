from sanitized_data_platform.application.services import ExtractionPlanningService
from sanitized_data_platform.domain.entities import MetadataObject, Relationship, SelectionCriteria
from sanitized_data_platform.domain.enums import MetadataObjectType

from tests.fakes import InMemoryMetadataCatalogRepository, sample_source


def extraction_metadata_objects() -> list[MetadataObject]:
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


def extraction_relationships() -> list[Relationship]:
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


def test_extraction_plan_creation_for_root_object_only():
    service = ExtractionPlanningService(
        InMemoryMetadataCatalogRepository(
            extraction_metadata_objects(),
            extraction_relationships(),
        )
    )

    plan = service.build_plan(
        source_id="source-crm-replica",
        root_object_id="table-customers",
        criteria=[SelectionCriteria(field_name="customer_id", operator="eq", value="42")],
        include_related=False,
    )

    assert plan.root.object_id == "table-customers"
    assert plan.root.criteria[0].field_name == "customer_id"
    assert plan.selected_object_ids == ("table-customers",)
    assert plan.selected_relationship_ids == ()


def test_extraction_plan_can_carry_selected_columns_for_root_table():
    service = ExtractionPlanningService(
        InMemoryMetadataCatalogRepository(
            extraction_metadata_objects(),
            extraction_relationships(),
        )
    )

    plan = service.build_plan(
        source_id="source-crm-replica",
        root_object_id="table-customers",
        selected_columns=["customer_id"],
        include_related=False,
    )

    assert plan.root.object_id == "table-customers"
    assert plan.root.selected_columns == ("customer_id",)


def test_extraction_plan_expands_through_active_foreign_key_relationships():
    service = ExtractionPlanningService(
        InMemoryMetadataCatalogRepository(
            extraction_metadata_objects(),
            extraction_relationships(),
        )
    )

    plan = service.build_plan(
        source_id="source-crm-replica",
        root_object_id="table-customers",
        include_related=True,
        max_depth=1,
    )

    assert plan.traversal_rule.include_related is True
    assert set(plan.selected_object_ids) == {"table-customers", "table-orders"}
    assert plan.selected_relationship_ids == (
        "fk:orders.customer_id->customers.customer_id",
    )


def test_extraction_plan_handles_absent_relationships_without_expansion():
    service = ExtractionPlanningService(
        InMemoryMetadataCatalogRepository(extraction_metadata_objects(), [])
    )

    plan = service.build_plan(
        source_id="source-crm-replica",
        root_object_id="table-customers",
        include_related=True,
        max_depth=1,
    )

    assert plan.selected_object_ids == ("table-customers",)
    assert plan.selected_relationship_ids == ()
    assert plan.notes == (
        "No active foreign-key relationships expanded from the selected root.",
    )


def test_extraction_plan_can_start_from_column_and_expand_to_related_tables():
    service = ExtractionPlanningService(
        InMemoryMetadataCatalogRepository(
            extraction_metadata_objects(),
            extraction_relationships(),
        )
    )

    plan = service.build_plan(
        source_id="source-crm-replica",
        root_object_id="column-customers-customer-id",
        include_related=True,
        max_depth=1,
    )

    assert set(plan.selected_object_ids) == {"column-customers-customer-id", "table-orders"}
    assert plan.selected_relationship_ids == (
        "fk:orders.customer_id->customers.customer_id",
    )
