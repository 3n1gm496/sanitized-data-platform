import time
from datetime import datetime, timezone

from sanitized_data_platform.adapters.postgres.control_plane import (
    ControlPlaneJsonStore,
    PostgresAuditEventRepository,
    PostgresBaselineAssetRepository,
    PostgresDataSourceRepository,
    PostgresLineageRepository,
    PostgresMetadataCatalogRepository,
    PostgresPublishJobRepository,
    PostgresSystemRepository,
    PostgresValidationRepository,
    SqliteBackend,
)
from sanitized_data_platform.bootstrap.production import PublishJobPollingQueue
from sanitized_data_platform.domain.entities import (
    AuditEvent,
    BaselineTableAsset,
    DataSource,
    LineageRecord,
    MetadataObject,
    PublishJob,
    System,
    ValidationCheckResult,
    ValidationReport,
)
from sanitized_data_platform.domain.enums import (
    DatabaseEngine,
    ExtractionArtifactFormat,
    JobStatus,
    MetadataObjectType,
    ValidationSeverity,
    ValidationStatus,
)


def _store(tmp_path) -> ControlPlaneJsonStore:
    store = ControlPlaneJsonStore(SqliteBackend(str(tmp_path / "control-plane.db")))
    store.run_migrations()
    return store


def test_control_plane_store_runs_migrations_and_pings(tmp_path):
    store = _store(tmp_path)

    assert store.ping() is True


def test_system_and_data_source_repositories_roundtrip(tmp_path):
    store = _store(tmp_path)
    systems = PostgresSystemRepository(store)
    sources = PostgresDataSourceRepository(store)

    systems.save(System(system_id="crm", name="CRM"))
    sources.save(
        DataSource(
            source_id="source-crm",
            system_id="crm",
            system_name="CRM",
            engine_type=DatabaseEngine.POSTGRES,
            endpoint="postgres.internal",
            database_name="crm",
        )
    )

    assert systems.get_by_id("crm").name == "CRM"
    assert sources.get_active_by_system_id("crm").source_id == "source-crm"


def test_publish_job_repository_preserves_status_and_timestamps(tmp_path):
    store = _store(tmp_path)
    jobs = PostgresPublishJobRepository(store)
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = PublishJob.create(
        job_id="job-1",
        source_id="source-crm",
        sanitized_baseline_id="baseline-1",
        baseline_validation_status=ValidationStatus.PASSED,
        baseline_validation_warning_count=0,
        baseline_validation_error_count=0,
        baseline_validated_at=created_at,
        target_environment_id="env-dev",
        dataset_profile_id="profile-1",
        requested_by="developer@example.internal",
        created_at=created_at,
    ).transition_to(
        JobStatus.COMPLETED,
        updated_at=created_at,
        execution_summary={"rowsImported": 5},
    )

    jobs.add(job)
    loaded = jobs.get_by_id("job-1")

    assert loaded is not None
    assert loaded.status == JobStatus.COMPLETED
    assert loaded.execution_summary["rowsImported"] == 5
    assert loaded.created_at == created_at


def test_validation_repository_returns_latest_report_for_baseline(tmp_path):
    store = _store(tmp_path)
    reports = PostgresValidationRepository(store)
    older = ValidationReport(
        report_id="report-1",
        baseline_id="baseline-1",
        status=ValidationStatus.PASSED,
        checks=(
            ValidationCheckResult(
                check_name="check-a",
                severity=ValidationSeverity.ERROR,
                passed=True,
            ),
        ),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    newer = ValidationReport(
        report_id="report-2",
        baseline_id="baseline-1",
        status=ValidationStatus.PASSED_WITH_WARNINGS,
        checks=(
            ValidationCheckResult(
                check_name="check-b",
                severity=ValidationSeverity.WARNING,
                passed=True,
            ),
        ),
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    reports.save(older)
    reports.save(newer)

    latest = reports.get_latest_for_baseline("baseline-1")

    assert latest is not None
    assert latest.report_id == "report-2"
    assert latest.warning_count == 1


def test_baseline_asset_replace_is_idempotent_for_baseline(tmp_path):
    store = _store(tmp_path)
    assets = PostgresBaselineAssetRepository(store)

    assets.replace_for_baseline(
        "baseline-1",
        [
            BaselineTableAsset(
                asset_id="asset-1",
                baseline_id="baseline-1",
                source_id="source-crm",
                root_object_id="table:source-crm:public.customers",
                artifact_format=ExtractionArtifactFormat.JSONL,
                artifact_path="/tmp/customers.jsonl",
                row_count=10,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                import_order=1,
            )
        ],
    )
    assets.replace_for_baseline(
        "baseline-1",
        [
            BaselineTableAsset(
                asset_id="asset-2",
                baseline_id="baseline-1",
                source_id="source-crm",
                root_object_id="table:source-crm:public.orders",
                artifact_format=ExtractionArtifactFormat.JSONL,
                artifact_path="/tmp/orders.jsonl",
                row_count=20,
                created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                import_order=1,
            )
        ],
    )

    listed = assets.list_for_baseline("baseline-1")

    assert [item.asset_id for item in listed] == ["asset-2"]


def test_metadata_catalog_repository_filters_by_object_type(tmp_path):
    store = _store(tmp_path)
    catalog = PostgresMetadataCatalogRepository(store)
    catalog.upsert_objects(
        [
            MetadataObject(
                object_id="table-1",
                source_id="source-crm",
                system_id="crm",
                system_name="CRM",
                object_type=MetadataObjectType.TABLE,
                name="customers",
                qualified_name="public.customers",
                container_name="public",
            ),
            MetadataObject(
                object_id="column-1",
                source_id="source-crm",
                system_id="crm",
                system_name="CRM",
                object_type=MetadataObjectType.COLUMN,
                name="email",
                qualified_name="public.customers.email",
                container_name="customers",
                parent_object_id="table-1",
                logical_data_type="string",
            ),
        ]
    )

    tables = catalog.list_objects("source-crm", object_type=MetadataObjectType.TABLE)

    assert len(tables) == 1
    assert tables[0].name == "customers"


def test_audit_and_lineage_repositories_filter_related_records(tmp_path):
    store = _store(tmp_path)
    audits = PostgresAuditEventRepository(store)
    lineage = PostgresLineageRepository(store)

    audits.add(
        AuditEvent(
            event_id="audit-1",
            event_type="publish_job_completed",
            actor="system",
            subject_type="publish_job",
            subject_id="job-1",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    lineage.add(
        LineageRecord(
            record_id="lineage-1",
            source_type="sanitized_baseline",
            source_id="baseline-1",
            target_type="publish_job",
            target_id="job-1",
            event_type="baseline_published",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )

    assert audits.list_for_subject("job-1")[0].event_id == "audit-1"
    assert lineage.list_related(reference_type="publish_job", reference_id="job-1")[0].record_id == "lineage-1"


def test_persistent_publish_queue_uses_leases_and_recovers_after_expiry(tmp_path):
    store = _store(tmp_path)
    jobs = PostgresPublishJobRepository(store)
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    jobs.add(
        PublishJob.create(
            job_id="job-1",
            source_id="source-crm",
            sanitized_baseline_id="baseline-1",
            baseline_validation_status=ValidationStatus.PASSED,
            baseline_validation_warning_count=0,
            baseline_validation_error_count=0,
            baseline_validated_at=created_at,
            target_environment_id="env-dev",
            dataset_profile_id="profile-1",
            requested_by="developer@example.internal",
            created_at=created_at,
        )
    )
    queue_a = PublishJobPollingQueue(
        store=store,
        jobs=jobs,
        worker_id="worker-a",
        lease_seconds=1,
    )
    queue_b = PublishJobPollingQueue(
        store=store,
        jobs=jobs,
        worker_id="worker-b",
        lease_seconds=1,
    )

    first_claim = queue_a.dequeue()
    blocked_claim = queue_b.dequeue()
    time.sleep(1.1)
    recovered_claim = queue_b.dequeue()
    queue_b.complete("job-1")

    assert first_claim == "job-1"
    assert blocked_claim is None
    assert recovered_claim == "job-1"
    assert store.count_active_leases() == 0
