from dataclasses import replace

from sanitized_data_platform.application.dto import CreateExtractionJobCommand
from sanitized_data_platform.application.services import (
    ExtractionJobMonitoringService,
    ExtractionJobRequestService,
    ExtractionPlanningService,
)
from sanitized_data_platform.workers.extraction_worker import ExtractionWorker

from tests.fakes import (
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryDataSourceRepository,
    InMemoryExtractionArtifactRepository,
    InMemoryExtractionJobRepository,
    InMemoryExtractionPlanSnapshotRepository,
    InMemoryExtractionQueue,
    InMemoryLineageRepository,
    InMemoryMetadataCatalogRepository,
    InMemoryValidationRepository,
    SequentialIdGenerator,
    StubExtractionPipeline,
    sample_source,
)
from tests.test_extraction_planning import (
    extraction_metadata_objects,
    extraction_relationships,
)


def build_extraction_services():
    source_repo = InMemoryDataSourceRepository([sample_source()])
    extraction_job_repo = InMemoryExtractionJobRepository()
    artifact_repo = InMemoryExtractionArtifactRepository()
    snapshot_repo = InMemoryExtractionPlanSnapshotRepository()
    extraction_queue = InMemoryExtractionQueue()
    audit_repo = InMemoryAuditEventRepository()
    planning = ExtractionPlanningService(
        InMemoryMetadataCatalogRepository(
            extraction_metadata_objects(),
            extraction_relationships(),
        )
    )
    clock = FakeClock()
    ids = SequentialIdGenerator()
    request = ExtractionJobRequestService(
        data_sources=source_repo,
        extraction_jobs=extraction_job_repo,
        extraction_plan_snapshots=snapshot_repo,
        extraction_queue=extraction_queue,
        planning=planning,
        audits=audit_repo,
        clock=clock,
        ids=ids,
    )
    monitoring = ExtractionJobMonitoringService(extraction_job_repo)
    return (
        request,
        monitoring,
        extraction_job_repo,
        artifact_repo,
        snapshot_repo,
        extraction_queue,
        audit_repo,
        planning,
        clock,
        ids,
        source_repo,
    )


def test_extraction_job_creation_and_queue_handoff():
    request, _, _, _, snapshot_repo, extraction_queue, _, _, _, _, _ = build_extraction_services()

    job = request.create_job(
        CreateExtractionJobCommand(
            source_id="source-crm-replica",
            root_object_id="table-customers",
            criteria=[],
            include_related=True,
            max_depth=1,
            requested_by="developer@example.internal",
            selected_columns=["customer_id"],
        )
    )

    assert job.job_id == "extraction-1"
    assert job.system_id == "crm"
    assert job.plan_snapshot_id == "extraction-plan-snapshot-1"
    snapshot = snapshot_repo.get_by_id(job.plan_snapshot_id)
    assert snapshot is not None
    assert snapshot.root.selected_columns == ("customer_id",)
    assert snapshot.root.artifact_kind.value == "sample"
    assert set(snapshot.selected_object_ids) == {"table-customers", "table-orders"}
    assert job.status == "requested"
    assert extraction_queue.dequeue() == job.job_id


def test_extraction_job_monitoring_lists_and_reads_jobs():
    request, monitoring, _, _, _, _, _, _, _, _, _ = build_extraction_services()
    created = request.create_job(
        CreateExtractionJobCommand(
            source_id="source-crm-replica",
            root_object_id="table-customers",
            criteria=[],
            include_related=False,
            max_depth=1,
            requested_by="developer@example.internal",
            selected_columns=["customer_id"],
        )
    )

    listed = monitoring.list_jobs()
    detail = monitoring.get_job(created.job_id)

    assert listed[0].job_id == created.job_id
    assert detail.root_object_id == "table-customers"


def test_extraction_worker_processes_job_to_completion():
    (
        request,
        _monitoring,
        extraction_job_repo,
        artifact_repo,
        snapshot_repo,
        extraction_queue,
        audit_repo,
        planning,
        clock,
        ids,
        source_repo,
    ) = build_extraction_services()
    lineage_repo = InMemoryLineageRepository()
    validation_repo = InMemoryValidationRepository([])
    created = request.create_job(
        CreateExtractionJobCommand(
            source_id="source-crm-replica",
            root_object_id="table-customers",
            criteria=[],
            include_related=True,
            max_depth=1,
            requested_by="developer@example.internal",
        )
    )

    snapshot = snapshot_repo.get_by_id(created.plan_snapshot_id)
    assert snapshot is not None
    snapshot_repo.add(
        replace(
            snapshot,
            selected_object_ids=("table-customers",),
            selected_relationship_ids=(),
        )
    )

    worker = ExtractionWorker(
        queue=extraction_queue,
        jobs=extraction_job_repo,
        artifacts=artifact_repo,
        plan_snapshots=snapshot_repo,
        pipeline=StubExtractionPipeline(),
        audits=audit_repo,
        lineage=lineage_repo,
        validations=validation_repo,
        clock=clock,
        ids=ids,
    )

    processed_job_id = worker.process_next_job()
    completed_job = extraction_job_repo.get_by_id(created.job_id)
    audit_events = audit_repo.list_for_subject(created.job_id)
    lineage_records = lineage_repo.list_related(
        reference_type="extraction_job",
        reference_id=created.job_id,
    )
    artifact_lineage_records = lineage_repo.list_related(
        reference_type="extraction_artifact",
        reference_id="extraction-artifact-1",
    )

    assert processed_job_id == created.job_id
    assert completed_job is not None
    assert completed_job.status.value == "completed"
    assert completed_job.extraction_artifact_id == "extraction-artifact-1"
    assert completed_job.execution_summary["extractionStrategy"] == "stubbed-extraction"
    assert completed_job.execution_summary["selectedObjectCount"] == 1
    artifact = artifact_repo.get_by_id("extraction-artifact-1")
    assert artifact is not None
    assert artifact.kind.value == "sample"
    assert artifact.job_id == created.job_id
    assert artifact.artifact_path == "/tmp/stub-extraction-artifact.jsonl"
    assert artifact.row_count == 1
    assert artifact.file_size_bytes == 128
    assert artifact.checksum == "stub-checksum"
    assert artifact.column_count == 0
    assert [record.event_type for record in lineage_records] == [
        "extraction_from_source",
        "extraction_root_selected",
        "extraction_plan_includes_object",
        "extraction_executed_from_plan_snapshot",
        "extraction_materialized_artifact",
    ]
    assert [record.event_type for record in artifact_lineage_records] == [
        "extraction_materialized_artifact"
    ]
    assert artifact_lineage_records[0].source_type == "extraction_job"
    assert artifact_lineage_records[0].source_id == created.job_id
    assert lineage_records[0].details["systemId"] == "crm"
    snapshot_record = next(
        record for record in lineage_records if record.event_type == "extraction_executed_from_plan_snapshot"
    )
    assert snapshot_record.source_type == "extraction_plan_snapshot"
    assert snapshot_record.source_id == created.plan_snapshot_id
    assert [event.event_type for event in audit_events] == [
        "extraction_job_requested",
        "extraction_job_started",
        "extraction_job_completed",
    ]


def test_extraction_worker_records_full_artifact_kind():
    (
        request,
        _monitoring,
        extraction_job_repo,
        artifact_repo,
        snapshot_repo,
        extraction_queue,
        audit_repo,
        planning,
        clock,
        ids,
        source_repo,
    ) = build_extraction_services()
    lineage_repo = InMemoryLineageRepository()
    validation_repo = InMemoryValidationRepository([])
    created = request.create_job(
        CreateExtractionJobCommand(
            source_id="source-crm-replica",
            root_object_id="table-customers",
            criteria=[],
            include_related=False,
            max_depth=1,
            requested_by="developer@example.internal",
            artifact_kind="full",
        )
    )

    worker = ExtractionWorker(
        queue=extraction_queue,
        jobs=extraction_job_repo,
        artifacts=artifact_repo,
        plan_snapshots=snapshot_repo,
        pipeline=StubExtractionPipeline(),
        audits=audit_repo,
        lineage=lineage_repo,
        validations=validation_repo,
        clock=clock,
        ids=ids,
    )

    worker.process_next_job()
    artifact = artifact_repo.get_by_id("extraction-artifact-1")

    assert artifact is not None
    assert artifact.kind.value == "full"
