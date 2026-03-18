from dataclasses import replace
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
    sample_profile,
    sample_system,
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


def test_oracle_artifact_extraction_to_publish_flow_is_coherent():
    source_repo = InMemoryDataSourceRepository([sample_oracle_source()])
    target_repo = InMemoryTargetEnvironmentRepository([sample_oracle_target()])
    extraction_job_repo = InMemoryExtractionJobRepository()
    artifact_repo = InMemoryExtractionArtifactRepository()
    snapshot_repo = InMemoryExtractionPlanSnapshotRepository()
    extraction_queue = InMemoryExtractionQueue()
    artifact_publish_job_repo = InMemoryArtifactPublishJobRepository()
    artifact_publish_queue = InMemoryArtifactPublishQueue()
    audit_repo = InMemoryAuditEventRepository()
    clock = FakeClock()
    ids = SequentialIdGenerator()
    planning = ExtractionPlanningService(
        InMemoryMetadataCatalogRepository(
            oracle_metadata_objects(),
            oracle_relationships(),
        )
    )
    extraction_request = ExtractionJobRequestService(
        data_sources=source_repo,
        extraction_jobs=extraction_job_repo,
        extraction_plan_snapshots=snapshot_repo,
        extraction_queue=extraction_queue,
        planning=planning,
        audits=audit_repo,
        clock=clock,
        ids=ids,
    )
    created = extraction_request.create_job(
        CreateExtractionJobCommand(
            source_id="source-crm-oracle",
            root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
            criteria=[],
            include_related=False,
            max_depth=1,
            requested_by="developer@example.internal",
        )
    )
    extraction_worker = ExtractionWorker(
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
    extraction_worker.process_next_job()

    artifact_publish_request = ArtifactPublishRequestService(
        artifacts=artifact_repo,
        environments=target_repo,
        jobs=artifact_publish_job_repo,
        audits=audit_repo,
        queue=artifact_publish_queue,
        clock=clock,
        ids=ids,
    )
    artifact_publish_job = artifact_publish_request.create_job(
        CreateArtifactPublishJobCommand(
            extraction_artifact_id="extraction-artifact-1",
            target_environment_id="env-dev",
            requested_by="developer@example.internal",
        )
    )
    artifact_publish_worker = ArtifactPublishWorker(
        queue=artifact_publish_queue,
        jobs=artifact_publish_job_repo,
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
    artifact_publish_worker.process_next_job()

    completed = artifact_publish_job_repo.get_by_id(artifact_publish_job.job_id)
    assert completed is not None
    assert completed.status.value == "completed"
    assert completed.execution_summary["deliveryStrategy"] == "oracle-jsonl-root-table-import"


def test_oracle_baseline_refresh_to_publish_flow_is_coherent():
    system_repo = InMemorySystemRepository([sample_system()])
    source_repo = InMemoryDataSourceRepository([sample_oracle_source()])
    target_repo = InMemoryTargetEnvironmentRepository([sample_oracle_target()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    baseline_repo = InMemoryBaselineRepository([sample_oracle_baseline()])
    baseline_asset_repo = InMemoryBaselineAssetRepository()
    refresh_job_repo = InMemoryBaselineRefreshJobRepository()
    refresh_queue = InMemoryBaselineRefreshQueue()
    publish_job_repo = InMemoryPublishJobRepository()
    publish_queue = InMemoryJobQueue()
    audit_repo = InMemoryAuditEventRepository()
    validation_repo = InMemoryValidationRepository([sample_validation_report()])
    clock = FakeClock()
    ids = SequentialIdGenerator()

    refresh_request = BaselineRefreshRequestService(
        systems=system_repo,
        data_sources=source_repo,
        dataset_profiles=profile_repo,
        refresh_jobs=refresh_job_repo,
        refresh_queue=refresh_queue,
        audits=audit_repo,
        clock=clock,
        ids=ids,
    )
    refresh_job = refresh_request.create_job(
        CreateBaselineRefreshJobCommand(
            system_id="crm",
            dataset_profile_id="profile-full-sanitized",
            target_environment_type="dev",
            requested_by="steward@example.internal",
        )
    )
    refresh_worker = BaselineRefreshWorker(
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
        validations=validation_repo,
        clock=clock,
        ids=ids,
    )
    refresh_worker.process_next_job()

    publish_request = PublishRequestService(
        data_sources=source_repo,
        environments=target_repo,
        dataset_profiles=profile_repo,
        jobs=publish_job_repo,
        audits=audit_repo,
        queue=publish_queue,
        policy=AllowAllPolicy(),
        readiness=build_readiness_service(clock=clock),
        publish_source_resolution=PublishSourceResolutionService(
            BaselineSelectionService(
                baseline_repo,
                BaselineStorageReadinessService(baseline_asset_repo),
                BaselineValidationEligibilityService(
                    ValidationLookupService(validation_repo)
                ),
            )
        ),
        clock=clock,
        ids=ids,
    )
    publish_job = publish_request.create_job(
        CreatePublishJobCommand(
            source_id="source-crm-oracle",
            target_environment_id="env-dev",
            dataset_profile_id="profile-full-sanitized",
            requested_by="developer@example.internal",
        )
    )
    publish_worker = PublishWorker(
        queue=publish_queue,
        jobs=publish_job_repo,
        baselines=baseline_repo,
        data_sources=source_repo,
        environments=target_repo,
        dataset_profiles=profile_repo,
        pipeline=OracleBaselinePublishPipelineAdapter(
            baseline_assets=baseline_asset_repo,
            connect=lambda _endpoint: OraclePublishConnection([], {"CRM.CUSTOMERS": ("CUSTOMER_ID", "EMAIL"), "CRM.ORDERS": ("CUSTOMER_ID", "EMAIL")}),
        ),
        audits=audit_repo,
        lineage=InMemoryLineageRepository(),
        validations=validation_repo,
        clock=clock,
        ids=ids,
    )
    publish_worker.process_next_job()

    completed = publish_job_repo.get_by_id(publish_job.job_id)
    assert completed is not None
    assert completed.status.value == "completed"
    assert completed.execution_summary["baselineStrategy"] == "oracle-materialized-baseline"
