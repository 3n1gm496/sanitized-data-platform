from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import tempfile

from sanitized_data_platform.adapters.oracle.artifact_publish_pipeline import (
    OracleArtifactPublishPipelineAdapter,
)
from sanitized_data_platform.adapters.oracle.baseline_publish_pipeline import (
    OracleBaselinePublishPipelineAdapter,
)
from sanitized_data_platform.adapters.oracle.baseline_refresh_pipeline import (
    OracleBaselineRefreshPipelineAdapter,
)
from sanitized_data_platform.adapters.oracle.extraction_pipeline import (
    OracleExtractionPipelineAdapter,
)
from sanitized_data_platform.application.dto import (
    CreateArtifactPublishJobCommand,
    CreateBaselineRefreshJobCommand,
    CreateExtractionJobCommand,
    CreatePublishJobCommand,
)
from sanitized_data_platform.application.services import (
    ArtifactPublishRequestService,
    BaselineRefreshRequestService,
    BaselineSelectionService,
    BaselineStorageReadinessService,
    BaselineValidationEligibilityService,
    ExtractionJobRequestService,
    ExtractionPlanningService,
    PublishRequestService,
    PublishSourceResolutionService,
    ValidationLookupService,
)
from sanitized_data_platform.workers.artifact_publish_worker import ArtifactPublishWorker
from sanitized_data_platform.workers.baseline_refresh_worker import BaselineRefreshWorker
from sanitized_data_platform.workers.extraction_worker import ExtractionWorker
from sanitized_data_platform.workers.publish_worker import PublishWorker

from tests.fakes import (
    AllowAllPolicy,
    FakeClock,
    InMemoryArtifactPublishJobRepository,
    InMemoryArtifactPublishQueue,
    InMemoryAuditEventRepository,
    InMemoryBaselineAssetRepository,
    InMemoryBaselineRefreshJobRepository,
    InMemoryBaselineRefreshQueue,
    InMemoryBaselineRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemoryExtractionArtifactRepository,
    InMemoryExtractionJobRepository,
    InMemoryExtractionPlanSnapshotRepository,
    InMemoryExtractionQueue,
    InMemoryJobQueue,
    InMemoryLineageRepository,
    InMemoryMetadataCatalogRepository,
    InMemoryPublishJobRepository,
    InMemorySystemRepository,
    InMemoryTargetEnvironmentRepository,
    InMemoryValidationRepository,
    SequentialIdGenerator,
    build_readiness_service,
    sample_baseline_asset,
    sample_extraction_artifact,
    sample_profile,
    sample_validation_report,
)
from tests.oracle_helpers import (
    OracleExtractionConnection,
    OraclePublishConnection,
    oracle_metadata_objects,
    oracle_relationships,
    sample_oracle_baseline,
    sample_oracle_source,
    sample_oracle_target,
)


def test_oracle_extraction_worker_uses_real_pipeline_adapter():
    source_repo = InMemoryDataSourceRepository([sample_oracle_source()])
    extraction_job_repo = InMemoryExtractionJobRepository()
    artifact_repo = InMemoryExtractionArtifactRepository()
    snapshot_repo = InMemoryExtractionPlanSnapshotRepository()
    extraction_queue = InMemoryExtractionQueue()
    audit_repo = InMemoryAuditEventRepository()
    planning = ExtractionPlanningService(
        InMemoryMetadataCatalogRepository(
            oracle_metadata_objects(),
            oracle_relationships(),
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
    job = request.create_job(
        CreateExtractionJobCommand(
            source_id="source-crm-oracle",
            root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
            criteria=[],
            include_related=False,
            max_depth=1,
            requested_by="developer@example.internal",
        )
    )
    worker = ExtractionWorker(
        queue=extraction_queue,
        jobs=extraction_job_repo,
        artifacts=artifact_repo,
        plan_snapshots=snapshot_repo,
        pipeline=OracleExtractionPipelineAdapter(
            data_sources=source_repo,
            connect=lambda _endpoint: OracleExtractionConnection(
                row_count=2,
                sample_rows=[(1, "a@example.internal"), (2, "b@example.internal")],
                sample_columns=("CUSTOMER_ID", "EMAIL"),
                table_columns=("CUSTOMER_ID", "EMAIL"),
                pk_columns=("CUSTOMER_ID",),
                executed=[],
            ),
        ),
        audits=audit_repo,
        lineage=InMemoryLineageRepository(),
        validations=InMemoryValidationRepository([]),
        clock=clock,
        ids=ids,
    )

    worker.process_next_job()
    completed = extraction_job_repo.get_by_id(job.job_id)

    assert completed is not None
    assert completed.status.value == "completed"
    assert completed.execution_summary["extractionStrategy"] == "oracle-table-root"


def test_oracle_artifact_publish_worker_uses_real_pipeline_adapter():
    artifact_repo = InMemoryExtractionArtifactRepository()
    target_repo = InMemoryTargetEnvironmentRepository([sample_oracle_target()])
    job_repo = InMemoryArtifactPublishJobRepository()
    queue = InMemoryArtifactPublishQueue()
    audit_repo = InMemoryAuditEventRepository()
    clock = FakeClock()
    ids = SequentialIdGenerator()
    request = ArtifactPublishRequestService(
        artifacts=artifact_repo,
        environments=target_repo,
        jobs=job_repo,
        audits=audit_repo,
        queue=queue,
        clock=clock,
        ids=ids,
    )
    payload = '{"CUSTOMER_ID": 1, "EMAIL": "a@example.internal"}\n'
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write(payload)
        handle.flush()
        artifact_repo.add(
            replace(
                sample_extraction_artifact(),
                source_id="source-crm-oracle",
                root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
                artifact_path=handle.name,
                row_count=1,
                checksum=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            )
        )
        created = request.create_job(
            CreateArtifactPublishJobCommand(
                extraction_artifact_id="extraction-artifact-1",
                target_environment_id="env-dev",
                requested_by="developer@example.internal",
            )
        )
        worker = ArtifactPublishWorker(
            queue=queue,
            jobs=job_repo,
            artifacts=artifact_repo,
            environments=target_repo,
            pipeline=OracleArtifactPublishPipelineAdapter(
                connect=lambda _endpoint: OraclePublishConnection([], {"CRM.CUSTOMERS": ("CUSTOMER_ID", "EMAIL")})
            ),
            audits=audit_repo,
            lineage=InMemoryLineageRepository(),
            validations=InMemoryValidationRepository([]),
            clock=clock,
            ids=ids,
        )

        worker.process_next_job()

    completed = job_repo.get_by_id(created.job_id)
    assert completed is not None
    assert completed.status.value == "completed"
    assert completed.execution_summary["deliveryStrategy"] == "oracle-jsonl-root-table-import"


def test_oracle_baseline_refresh_worker_uses_real_pipeline_adapter():
    from tests.fakes import sample_system
    system_repo = InMemorySystemRepository([sample_system()])
    source_repo = InMemoryDataSourceRepository([sample_oracle_source()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    baseline_repo = InMemoryBaselineRepository([sample_oracle_baseline()])
    baseline_asset_repo = InMemoryBaselineAssetRepository()
    refresh_job_repo = InMemoryBaselineRefreshJobRepository()
    refresh_queue = InMemoryBaselineRefreshQueue()
    audit_repo = InMemoryAuditEventRepository()
    clock = FakeClock()
    ids = SequentialIdGenerator()
    request = BaselineRefreshRequestService(
        systems=system_repo,
        data_sources=source_repo,
        dataset_profiles=profile_repo,
        refresh_jobs=refresh_job_repo,
        refresh_queue=refresh_queue,
        audits=audit_repo,
        clock=clock,
        ids=ids,
    )
    created = request.create_job(
        CreateBaselineRefreshJobCommand(
            system_id="crm",
            dataset_profile_id="profile-full-sanitized",
            target_environment_type="dev",
            requested_by="steward@example.internal",
        )
    )
    worker = BaselineRefreshWorker(
        systems=system_repo,
        refresh_queue=refresh_queue,
        refresh_jobs=refresh_job_repo,
        baselines=baseline_repo,
        baseline_assets=baseline_asset_repo,
        data_sources=source_repo,
        dataset_profiles=profile_repo,
        pipeline=OracleBaselineRefreshPipelineAdapter(
            metadata_catalog=InMemoryMetadataCatalogRepository(
                oracle_metadata_objects(),
                oracle_relationships(),
            ),
            data_sources=source_repo,
            connect=lambda _endpoint: OracleExtractionConnection(
                row_count=1,
                sample_rows=[(1, "a@example.internal")],
                sample_columns=("CUSTOMER_ID", "EMAIL"),
                table_columns=("CUSTOMER_ID", "EMAIL"),
                pk_columns=("CUSTOMER_ID",),
                executed=[],
            ),
            clock=clock,
        ),
        audits=audit_repo,
        lineage=InMemoryLineageRepository(),
        validations=InMemoryValidationRepository([sample_validation_report()]),
        clock=clock,
        ids=ids,
    )

    worker.process_next_job()
    refreshed = refresh_job_repo.get_by_id(created.job_id)
    assert refreshed is not None
    assert refreshed.status.value == "completed"
    assert refreshed.result_summary["refreshStrategy"] == "oracle-materialized-baseline"


def test_oracle_publish_worker_uses_real_baseline_publish_pipeline():
    source_repo = InMemoryDataSourceRepository([sample_oracle_source()])
    target_repo = InMemoryTargetEnvironmentRepository([sample_oracle_target()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    baseline_repo = InMemoryBaselineRepository([sample_oracle_baseline()])
    baseline_asset_repo = InMemoryBaselineAssetRepository()
    job_repo = InMemoryPublishJobRepository()
    audit_repo = InMemoryAuditEventRepository()
    queue = InMemoryJobQueue()
    clock = FakeClock()
    ids = SequentialIdGenerator()
    payload = '{"CUSTOMER_ID": 1, "EMAIL": "a@example.internal"}\n'
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write(payload)
        handle.flush()
        baseline_asset_repo.replace_for_baseline(
            "baseline-crm-dev-v1",
            [
                replace(
                    sample_baseline_asset(),
                    source_id="source-crm-oracle",
                    root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
                    artifact_path=handle.name,
                    row_count=1,
                    checksum=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                )
            ],
        )
        request = PublishRequestService(
            data_sources=source_repo,
            environments=target_repo,
            dataset_profiles=profile_repo,
            jobs=job_repo,
            audits=audit_repo,
            queue=queue,
            policy=AllowAllPolicy(),
            readiness=build_readiness_service(clock=clock),
            publish_source_resolution=PublishSourceResolutionService(
                BaselineSelectionService(
                    baseline_repo,
                    BaselineStorageReadinessService(baseline_asset_repo),
                    BaselineValidationEligibilityService(
                        ValidationLookupService(InMemoryValidationRepository([sample_validation_report()]))
                    ),
                )
            ),
            clock=clock,
            ids=ids,
        )
        created = request.create_job(
            CreatePublishJobCommand(
                source_id="source-crm-oracle",
                target_environment_id="env-dev",
                dataset_profile_id="profile-full-sanitized",
                requested_by="developer@example.internal",
            )
        )
        worker = PublishWorker(
            queue=queue,
            jobs=job_repo,
            baselines=baseline_repo,
            data_sources=source_repo,
            environments=target_repo,
            dataset_profiles=profile_repo,
            pipeline=OracleBaselinePublishPipelineAdapter(
                baseline_assets=baseline_asset_repo,
                connect=lambda _endpoint: OraclePublishConnection([], {"CRM.CUSTOMERS": ("CUSTOMER_ID", "EMAIL")}),
            ),
            audits=audit_repo,
            lineage=InMemoryLineageRepository(),
            validations=InMemoryValidationRepository([sample_validation_report()]),
            clock=clock,
            ids=ids,
        )

        worker.process_next_job()

    completed = job_repo.get_by_id(created.job_id)
    assert completed is not None
    assert completed.status.value == "completed"
    assert completed.execution_summary["baselineStrategy"] == "oracle-materialized-baseline"
