from sanitized_data_platform.application.dto import CreateExtractionJobCommand
from sanitized_data_platform.application.services import (
    ExtractionJobRequestService,
    ExtractionPlanSnapshotQueryService,
    ExtractionPlanningService,
)

from tests.fakes import (
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryDataSourceRepository,
    InMemoryExtractionJobRepository,
    InMemoryExtractionPlanSnapshotRepository,
    InMemoryExtractionQueue,
    InMemoryMetadataCatalogRepository,
    SequentialIdGenerator,
    sample_source,
)
from tests.test_extraction_planning import (
    extraction_metadata_objects,
    extraction_relationships,
)


def test_snapshot_query_service_returns_persisted_plan_detail():
    source_repo = InMemoryDataSourceRepository([sample_source()])
    snapshot_repo = InMemoryExtractionPlanSnapshotRepository()
    request_service = ExtractionJobRequestService(
        data_sources=source_repo,
        extraction_jobs=InMemoryExtractionJobRepository(),
        extraction_plan_snapshots=snapshot_repo,
        extraction_queue=InMemoryExtractionQueue(),
        planning=ExtractionPlanningService(
            InMemoryMetadataCatalogRepository(
                extraction_metadata_objects(),
                extraction_relationships(),
            )
        ),
        audits=InMemoryAuditEventRepository(),
        clock=FakeClock(),
        ids=SequentialIdGenerator(),
    )
    created = request_service.create_job(
        CreateExtractionJobCommand(
            source_id="source-crm-replica",
            root_object_id="table-customers",
            criteria=[{"fieldName": "customer_id", "operator": "eq", "value": "42"}],
            include_related=True,
            max_depth=1,
            requested_by="developer@example.internal",
            selected_columns=["customer_id"],
        )
    )

    query_service = ExtractionPlanSnapshotQueryService(snapshot_repo)
    snapshot = query_service.get_snapshot(created.plan_snapshot_id)

    assert snapshot.snapshot_id == created.plan_snapshot_id
    assert snapshot.source_id == "source-crm-replica"
    assert snapshot.root_object_id == "table-customers"
    assert snapshot.include_related is True
    assert snapshot.max_depth == 1
    assert snapshot.criteria[0].field_name == "customer_id"
    assert snapshot.selected_columns == ["customer_id"]
    assert set(snapshot.selected_object_ids) == {"table-customers", "table-orders"}
    assert snapshot.selected_relationship_ids == [
        "fk:orders.customer_id->customers.customer_id"
    ]
