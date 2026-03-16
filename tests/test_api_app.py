from sanitized_data_platform.application.services import (
    BaselineEligibilityExplanationService,
    BaselineQueryService,
    BaselineRefreshMonitoringService,
    BaselineRefreshRequestService,
    CatalogQueryService,
    ClassificationQueryService,
    ExtractionJobMonitoringService,
    ExtractionJobRequestService,
    ExtractionArtifactQueryService,
    ExtractionArtifactLifecycleService,
    ExtractionPlanPreviewService,
    ExtractionPlanSnapshotQueryService,
    ExtractionPlanningService,
    GovernanceSummaryQueryService,
    JobMonitoringService,
    LineageQueryService,
    MetadataQueryService,
    PolicyCoverageQueryService,
    PolicyCoverageEvaluationService,
    PolicyQueryService,
    PublishRequestService,
    RelationshipQueryService,
    RefreshScheduleService,
    ValidationQueryService,
)
from sanitized_data_platform.interfaces.api.app import ApiApp
from sanitized_data_platform.domain.entities import (
    ExtractionArtifact,
    ExtractionJob,
    LineageRecord,
    MetadataObject,
    Relationship,
    TransformationPolicy,
)
from sanitized_data_platform.domain.enums import (
    ExtractionArtifactFormat,
    ExtractionArtifactKind,
    MetadataObjectType,
    TransformationType,
)

from tests.fakes import (
    AllowAllPolicy,
    FakeClock,
    InMemoryAuditEventRepository,
    InMemoryBaselineRepository,
    InMemoryBaselineRefreshJobRepository,
    InMemoryBaselineRefreshQueue,
    InMemoryBaselineRefreshScheduleRepository,
    InMemoryClassificationRepository,
    InMemoryDataSourceRepository,
    InMemoryDatasetProfileRepository,
    InMemoryExtractionJobRepository,
    InMemoryExtractionArtifactRepository,
    InMemoryExtractionPlanSnapshotRepository,
    InMemoryExtractionQueue,
    InMemoryJobQueue,
    InMemoryLineageRepository,
    InMemoryMetadataCatalogRepository,
    InMemoryPublishJobRepository,
    InMemorySystemRepository,
    InMemoryTargetEnvironmentRepository,
    InMemoryTransformationPolicyRepository,
    InMemoryValidationRepository,
    PublishValidationSummaryService,
    SequentialIdGenerator,
    StubBaselineRefreshPipeline,
    StubExtractionPipeline,
    ValidationLookupService,
    build_publish_source_resolution_service,
    build_readiness_service,
    sample_baseline,
    sample_classification_tags,
    sample_metadata_objects,
    sample_profile,
    sample_relationships,
    sample_sensitivity_tags,
    sample_source,
    sample_system,
    sample_target,
    sample_transformation_policies,
    sample_validation_report,
)


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


def build_api(
    *,
    transformation_policies: list[TransformationPolicy] | None = None,
) -> ApiApp:
    source_repo = InMemoryDataSourceRepository([sample_source()])
    system_repo = InMemorySystemRepository([sample_system()])
    target_repo = InMemoryTargetEnvironmentRepository([sample_target()])
    profile_repo = InMemoryDatasetProfileRepository([sample_profile()])
    baseline_repo = InMemoryBaselineRepository([sample_baseline()])
    refresh_job_repo = InMemoryBaselineRefreshJobRepository()
    refresh_queue = InMemoryBaselineRefreshQueue()
    refresh_schedule_repo = InMemoryBaselineRefreshScheduleRepository()
    extraction_job_repo = InMemoryExtractionJobRepository()
    extraction_artifact_repo = InMemoryExtractionArtifactRepository()
    extraction_snapshot_repo = InMemoryExtractionPlanSnapshotRepository()
    extraction_queue = InMemoryExtractionQueue()
    job_repo = InMemoryPublishJobRepository()
    audit_repo = InMemoryAuditEventRepository()
    lineage_repo = InMemoryLineageRepository()
    queue = InMemoryJobQueue()
    clock = FakeClock()
    ids = SequentialIdGenerator()
    seeded_job = ExtractionJob.create(
        job_id="extraction-existing",
        source_id="source-crm-replica",
        system_id="crm",
        plan_snapshot_id="extraction-plan-snapshot-existing",
        root_object_id="table-customers",
        criteria=(),
        include_related=False,
        max_depth=1,
        requested_by="developer@example.internal",
        created_at=clock.now(),
    )
    extraction_job_repo.add(seeded_job)
    extraction_artifact_repo.add(
        ExtractionArtifact(
            artifact_id="extraction-artifact-existing",
            job_id=seeded_job.job_id,
            source_id=seeded_job.source_id,
            root_object_id=seeded_job.root_object_id,
            kind=ExtractionArtifactKind.SAMPLE,
            artifact_format=ExtractionArtifactFormat.JSONL,
            artifact_path="/tmp/extraction-existing.jsonl",
            row_count=2,
            created_at=clock.now(),
            file_size_bytes=256,
            checksum="api-artifact-checksum",
            column_count=2,
        )
    )
    lineage_repo.add(
        LineageRecord(
            record_id="lineage-1",
            source_type="baseline_refresh_job",
            source_id="baseline-refresh-1",
            target_type="sanitized_baseline",
            target_id="baseline-crm-dev-v1",
            event_type="baseline_materialized",
            created_at=clock.now(),
            details={"baselineVersion": "2026.01.01.1"},
        )
    )
    lineage_repo.add(
        LineageRecord(
            record_id="lineage-2",
            source_type="sanitized_baseline",
            source_id="baseline-crm-dev-v1",
            target_type="publish_job",
            target_id="job-1",
            event_type="baseline_published",
            created_at=clock.now(),
            details={"baselineVersion": "2026.01.01.1"},
        )
    )
    lineage_repo.add(
        LineageRecord(
            record_id="lineage-3",
            source_type="data_source",
            source_id="source-crm-replica",
            target_type="extraction_job",
            target_id="extraction-1",
            event_type="extraction_from_source",
            created_at=clock.now(),
            details={"systemId": "crm", "selectedObjectCount": 2},
        )
    )
    lineage_repo.add(
        LineageRecord(
            record_id="lineage-4",
            source_type="metadata_object",
            source_id="table-customers",
            target_type="extraction_job",
            target_id="extraction-1",
            event_type="extraction_root_selected",
            created_at=clock.now(),
            details={"includeRelated": True, "maxDepth": 1},
        )
    )

    catalog = CatalogQueryService(system_repo, source_repo, target_repo, profile_repo)
    coverage = PolicyCoverageEvaluationService(
        metadata_catalog=InMemoryMetadataCatalogRepository(sample_metadata_objects()),
        policies=InMemoryTransformationPolicyRepository(sample_transformation_policies()),
        classifications=InMemoryClassificationRepository(sample_sensitivity_tags()),
        clock=clock,
    )
    requests = PublishRequestService(
        data_sources=source_repo,
        environments=target_repo,
        dataset_profiles=profile_repo,
        jobs=job_repo,
        audits=audit_repo,
        queue=queue,
        policy=AllowAllPolicy(),
        readiness=build_readiness_service(clock=clock),
        publish_source_resolution=build_publish_source_resolution_service(),
        clock=clock,
        ids=ids,
    )
    monitoring = JobMonitoringService(job_repo, audit_repo)
    metadata_queries = MetadataQueryService(
        systems=system_repo,
        data_sources=source_repo,
        metadata_catalog=InMemoryMetadataCatalogRepository(
            sample_metadata_objects(),
            sample_relationships(),
        ),
    )
    relationship_queries = RelationshipQueryService(
        systems=system_repo,
        data_sources=source_repo,
        metadata_catalog=InMemoryMetadataCatalogRepository(
            sample_metadata_objects(),
            sample_relationships(),
        ),
    )
    policy_queries = PolicyQueryService(
        systems=system_repo,
        data_sources=source_repo,
        policies=InMemoryTransformationPolicyRepository(
            sample_transformation_policies()
            if transformation_policies is None
            else transformation_policies
        ),
    )
    policy_coverage_queries = PolicyCoverageQueryService(
        systems=system_repo,
        data_sources=source_repo,
        coverage=coverage,
    )
    baseline_queries = BaselineQueryService(
        systems=system_repo,
        baselines=baseline_repo,
        validations=ValidationLookupService(
            InMemoryValidationRepository([sample_validation_report()])
        ),
        validation_summary=PublishValidationSummaryService(),
        eligibility=BaselineEligibilityExplanationService(),
    )
    baseline_refresh_requests = BaselineRefreshRequestService(
        systems=system_repo,
        data_sources=source_repo,
        dataset_profiles=profile_repo,
        refresh_jobs=refresh_job_repo,
        refresh_queue=refresh_queue,
        audits=audit_repo,
        clock=clock,
        ids=ids,
    )
    baseline_refresh_monitoring = BaselineRefreshMonitoringService(refresh_job_repo)
    lineage_queries = LineageQueryService(lineage_repo)
    refresh_schedules = RefreshScheduleService(
        systems=system_repo,
        dataset_profiles=profile_repo,
        schedules=refresh_schedule_repo,
        clock=clock,
        ids=ids,
    )
    validation_queries = ValidationQueryService(
        baselines=baseline_repo,
        validations=ValidationLookupService(
            InMemoryValidationRepository([sample_validation_report()])
        ),
    )
    classification_queries = ClassificationQueryService(
        systems=system_repo,
        data_sources=source_repo,
        classifications=InMemoryClassificationRepository(sample_classification_tags()),
    )
    extraction_plan_previews = ExtractionPlanPreviewService(
        ExtractionPlanningService(
            InMemoryMetadataCatalogRepository(
                preview_metadata_objects(),
                preview_relationships(),
            )
        )
    )
    extraction_planning = ExtractionPlanningService(
        InMemoryMetadataCatalogRepository(
            preview_metadata_objects(),
            preview_relationships(),
        )
    )
    extraction_job_requests = ExtractionJobRequestService(
        data_sources=source_repo,
        extraction_jobs=extraction_job_repo,
        extraction_plan_snapshots=extraction_snapshot_repo,
        extraction_queue=extraction_queue,
        planning=extraction_planning,
        audits=audit_repo,
        clock=clock,
        ids=ids,
    )
    extraction_job_monitoring = ExtractionJobMonitoringService(extraction_job_repo)
    extraction_artifacts = ExtractionArtifactQueryService(
        jobs=extraction_job_repo,
        artifacts=extraction_artifact_repo,
        lifecycle=ExtractionArtifactLifecycleService(
            artifacts=extraction_artifact_repo,
            clock=clock,
        ),
    )
    extraction_plan_snapshots = ExtractionPlanSnapshotQueryService(extraction_snapshot_repo)
    governance_summary_queries = GovernanceSummaryQueryService(
        systems=system_repo,
        data_sources=source_repo,
        metadata_catalog=InMemoryMetadataCatalogRepository(
            sample_metadata_objects(),
            sample_relationships(),
        ),
        classifications=InMemoryClassificationRepository(sample_sensitivity_tags()),
        policies=InMemoryTransformationPolicyRepository(sample_transformation_policies()),
        coverage=coverage,
    )
    return ApiApp(
        baselines=baseline_queries,
        baseline_refresh_monitoring=baseline_refresh_monitoring,
        baseline_refresh_requests=baseline_refresh_requests,
        catalog=catalog,
        classification_queries=classification_queries,
        extraction_job_monitoring=extraction_job_monitoring,
        extraction_job_requests=extraction_job_requests,
        extraction_artifacts=extraction_artifacts,
        extraction_plan_previews=extraction_plan_previews,
        extraction_plan_snapshots=extraction_plan_snapshots,
        governance_summary_queries=governance_summary_queries,
        lineage_queries=lineage_queries,
        metadata_queries=metadata_queries,
        relationship_queries=relationship_queries,
        policy_queries=policy_queries,
        policy_coverage_queries=policy_coverage_queries,
        publish_requests=requests,
        refresh_schedules=refresh_schedules,
        validation_queries=validation_queries,
        job_monitoring=monitoring,
    )


def test_api_lists_systems_and_creates_job():
    app = build_api()

    systems_response = app.handle("GET", "/api/v1/systems")
    create_response = app.handle(
        "POST",
        "/api/v1/jobs",
        body={
            "sourceId": "source-crm-replica",
            "targetEnvironmentId": "env-dev",
            "datasetProfileId": "profile-full-sanitized",
            "requestedBy": "developer@example.internal",
        },
    )

    assert systems_response.status_code == 200
    assert systems_response.body[0]["name"] == "CRM"
    assert create_response.status_code == 202
    assert create_response.body["status"] == "pending"
    assert create_response.body["sanitized_baseline_id"] == "baseline-crm-dev-v1"
    assert create_response.body["baseline_validation_summary"]["status"] == "passed"


def test_api_previews_root_only_extraction_plan():
    app = build_api()

    response = app.handle(
        "POST",
        "/api/v1/extraction-plans/preview",
        body={
            "sourceId": "source-crm-replica",
            "rootObjectId": "table-customers",
            "criteria": [
                {"fieldName": "customer_id", "operator": "eq", "value": "42"}
            ],
            "includeRelated": False,
            "maxDepth": 1,
        },
    )

    assert response.status_code == 200
    assert response.body["root_object_id"] == "table-customers"
    assert response.body["criteria"][0]["field_name"] == "customer_id"
    assert response.body["selected_object_ids"] == ["table-customers"]
    assert response.body["selected_relationship_ids"] == []


def test_api_previews_extraction_plan_with_selected_columns():
    app = build_api()

    response = app.handle(
        "POST",
        "/api/v1/extraction-plans/preview",
        body={
            "sourceId": "source-crm-replica",
            "rootObjectId": "table-customers",
            "selectedColumns": ["customer_id"],
            "includeRelated": False,
            "maxDepth": 1,
        },
    )

    assert response.status_code == 200
    assert response.body["root_object_id"] == "table-customers"
    assert response.body["selected_columns"] == ["customer_id"]
    assert response.body["selected_object_ids"] == ["table-customers"]


def test_api_previews_fk_expanded_extraction_plan():
    app = build_api()

    response = app.handle(
        "POST",
        "/api/v1/extraction-plans/preview",
        body={
            "sourceId": "source-crm-replica",
            "rootObjectId": "table-customers",
            "includeRelated": True,
            "maxDepth": 1,
        },
    )

    assert response.status_code == 200
    assert response.body["include_related"] is True
    assert set(response.body["selected_object_ids"]) == {"table-customers", "table-orders"}
    assert response.body["selected_relationship_ids"] == [
        "fk:orders.customer_id->customers.customer_id"
    ]


def test_api_creates_and_lists_extraction_jobs():
    app = build_api()

    create_response = app.handle(
        "POST",
        "/api/v1/extraction-jobs",
        body={
            "sourceId": "source-crm-replica",
            "rootObjectId": "table-customers",
            "criteria": [],
            "includeRelated": True,
            "maxDepth": 1,
            "requestedBy": "developer@example.internal",
        },
    )
    list_response = app.handle("GET", "/api/v1/extraction-jobs")
    detail_response = app.handle(
        "GET",
        f"/api/v1/extraction-jobs/{create_response.body['job_id']}",
    )

    assert create_response.status_code == 202
    assert create_response.body["system_id"] == "crm"
    assert create_response.body["status"] == "requested"
    assert create_response.body["plan_snapshot_id"] == "extraction-plan-snapshot-1"
    assert list_response.status_code == 200
    assert list_response.body[0]["job_id"] == create_response.body["job_id"]
    assert detail_response.status_code == 200
    assert detail_response.body["root_object_id"] == "table-customers"


def test_api_exposes_extraction_job_artifact():
    app = build_api()

    response = app.handle(
        "GET",
        "/api/v1/extraction-jobs/extraction-existing/artifact",
    )

    assert response.status_code == 200
    assert response.body["artifact_id"] == "extraction-artifact-existing"
    assert response.body["job_id"] == "extraction-existing"
    assert response.body["kind"] == "sample"
    assert response.body["artifact_format"] == "jsonl"
    assert response.body["artifact_path"] == "/tmp/extraction-existing.jsonl"
    assert response.body["file_size_bytes"] == 256
    assert response.body["checksum"] == "api-artifact-checksum"
    assert response.body["column_count"] == 2
    assert response.body["status"] == "available"
    assert response.body["available"] is True


def test_api_exposes_extraction_plan_snapshot_detail():
    app = build_api()

    create_response = app.handle(
        "POST",
        "/api/v1/extraction-jobs",
        body={
            "sourceId": "source-crm-replica",
            "rootObjectId": "table-customers",
            "criteria": [
                {"fieldName": "customer_id", "operator": "eq", "value": "42"}
            ],
            "includeRelated": True,
            "maxDepth": 1,
            "requestedBy": "developer@example.internal",
        },
    )
    snapshot_id = create_response.body["plan_snapshot_id"]

    detail_response = app.handle(
        "GET",
        f"/api/v1/extraction-plan-snapshots/{snapshot_id}",
    )

    assert detail_response.status_code == 200
    assert detail_response.body["snapshot_id"] == snapshot_id
    assert detail_response.body["root_object_id"] == "table-customers"
    assert detail_response.body["include_related"] is True
    assert detail_response.body["criteria"][0]["field_name"] == "customer_id"
    assert set(detail_response.body["selected_object_ids"]) == {
        "table-customers",
        "table-orders",
    }
    assert detail_response.body["selected_relationship_ids"] == [
        "fk:orders.customer_id->customers.customer_id"
    ]


def test_api_exposes_metadata_policies_and_policy_coverage():
    app = build_api()

    metadata_response = app.handle("GET", "/api/v1/metadata/systems/crm")
    classifications_response = app.handle(
        "GET",
        "/api/v1/metadata/systems/crm/classifications",
        query={"classificationStatus": "non_sensitive"},
    )
    governance_response = app.handle(
        "GET",
        "/api/v1/metadata/systems/crm/governance-summary",
    )
    relationships_response = app.handle(
        "GET",
        "/api/v1/metadata/systems/crm/relationships",
        query={"relationshipType": "foreign_key"},
    )
    policies_response = app.handle(
        "GET",
        "/api/v1/policies",
        query={"systemId": "crm", "objectName": "crm.customers", "columnName": "email"},
    )
    coverage_response = app.handle("GET", "/api/v1/policy-coverage/crm")

    assert metadata_response.status_code == 200
    assert metadata_response.body["system_id"] == "crm"
    assert len(metadata_response.body["items"]) == 3

    assert classifications_response.status_code == 200
    assert classifications_response.body["system_id"] == "crm"
    assert classifications_response.body["filters"]["classificationStatus"] == "non_sensitive"
    assert len(classifications_response.body["items"]) == 1
    assert classifications_response.body["items"][0]["object_id"] == "column-customers-status"

    assert governance_response.status_code == 200
    assert governance_response.body["system_id"] == "crm"
    assert any(
        item["object_id"] == "column-customers-email"
        and item["coverage_state"] == "complete"
        for item in governance_response.body["items"]
    )
    assert any(
        item["object_id"] == "column-customers-status"
        and item["gap_types"] == ["missing_classification"]
        for item in governance_response.body["items"]
    )

    assert relationships_response.status_code == 200
    assert relationships_response.body["system_id"] == "crm"
    assert relationships_response.body["filters"]["relationshipType"] == "foreign_key"
    assert len(relationships_response.body["items"]) == 1
    assert relationships_response.body["items"][0]["relationship_type"] == "foreign_key"

    assert policies_response.status_code == 200
    assert policies_response.body["filters"]["systemId"] == "crm"
    assert policies_response.body["items"][0]["column_name"] == "email"
    assert policies_response.body["items"][0]["canonical_object_id"] is None
    assert policies_response.body["items"][0]["legacy_object_name"] == "crm.customers"
    assert policies_response.body["items"][0]["target_mode"] == "legacy_fallback"

    assert coverage_response.status_code == 200
    assert coverage_response.body["system_id"] == "crm"
    assert coverage_response.body["publish_ready"] is True
    assert coverage_response.body["informational_gap_count"] == 1


def test_api_exposes_canonical_policy_target_visibility():
    source = sample_source()
    app = build_api(
        transformation_policies=[
            TransformationPolicy(
                policy_id="policy-canonical-api",
                system_id=source.system_id,
                system_name=source.system_name,
                object_name="legacy.not-used",
                object_id="table-customers",
                column_name="email",
                sensitivity_tag="pii.email",
                transformation_type=TransformationType.HASHING,
            )
        ]
    )

    response = app.handle("GET", "/api/v1/policies", query={"systemId": "crm"})

    assert response.status_code == 200
    assert len(response.body["items"]) == 1
    item = response.body["items"][0]
    assert item["canonical_object_id"] == "table-customers"
    assert item["legacy_object_name"] == "legacy.not-used"
    assert item["target_mode"] == "canonical"


def test_api_filters_policies_by_target_mode():
    source = sample_source()
    app = build_api(
        transformation_policies=[
            TransformationPolicy(
                policy_id="policy-canonical-api",
                system_id=source.system_id,
                system_name=source.system_name,
                object_name="legacy.not-used",
                object_id="table-customers",
                column_name="email",
                sensitivity_tag="pii.email",
                transformation_type=TransformationType.HASHING,
            ),
            sample_transformation_policies()[0],
        ]
    )

    canonical_response = app.handle(
        "GET",
        "/api/v1/policies",
        query={"systemId": "crm", "targetMode": "canonical"},
    )
    legacy_response = app.handle(
        "GET",
        "/api/v1/policies",
        query={"systemId": "crm", "targetMode": "legacy_fallback"},
    )

    assert canonical_response.status_code == 200
    assert canonical_response.body["filters"] == {
        "systemId": "crm",
        "targetMode": "canonical",
    }
    assert len(canonical_response.body["items"]) == 1
    assert canonical_response.body["items"][0]["target_mode"] == "canonical"

    assert legacy_response.status_code == 200
    assert legacy_response.body["filters"] == {
        "systemId": "crm",
        "targetMode": "legacy_fallback",
    }
    assert len(legacy_response.body["items"]) == 1
    assert legacy_response.body["items"][0]["target_mode"] == "legacy_fallback"


def test_api_exposes_baseline_listing_and_detail():
    app = build_api()

    list_response = app.handle("GET", "/api/v1/baselines", query={"systemId": "crm"})
    detail_response = app.handle("GET", "/api/v1/baselines/baseline-crm-dev-v1")

    assert list_response.status_code == 200
    assert list_response.body["filters"]["systemId"] == "crm"
    assert list_response.body["items"][0]["baseline_id"] == "baseline-crm-dev-v1"
    assert list_response.body["items"][0]["publish_eligible"] is True
    assert list_response.body["items"][0]["eligibility"]["reason"] == "eligible"
    assert list_response.body["items"][0]["validation_summary"]["status"] == "passed"

    assert detail_response.status_code == 200
    assert detail_response.body["baseline_id"] == "baseline-crm-dev-v1"
    assert detail_response.body["publish_eligible"] is True
    assert detail_response.body["eligibility"]["reason"] == "eligible"
    assert detail_response.body["validation_summary"]["warning_count"] == 0


def test_api_exposes_validation_report_for_baseline():
    app = build_api()

    response = app.handle(
        "GET",
        "/api/v1/baselines/baseline-crm-dev-v1/validation",
    )

    assert response.status_code == 200
    assert response.body["baseline_id"] == "baseline-crm-dev-v1"
    assert response.body["status"] == "passed"
    assert response.body["publish_eligible"] is True
    assert response.body["checks"][0]["check_name"] == "referential_integrity"
    assert response.body["checks"][0]["severity"] == "info"


def test_api_exposes_baseline_refresh_job_lifecycle_views():
    app = build_api()

    create_response = app.handle(
        "POST",
        "/api/v1/baseline-refresh-jobs",
        body={
            "systemId": "crm",
            "datasetProfileId": "profile-full-sanitized",
            "targetEnvironmentType": "dev",
            "requestedBy": "steward@example.internal",
        },
    )
    list_response = app.handle("GET", "/api/v1/baseline-refresh-jobs")
    detail_response = app.handle(
        "GET",
        f"/api/v1/baseline-refresh-jobs/{create_response.body['job_id']}",
    )

    assert create_response.status_code == 202
    assert create_response.body["status"] == "requested"
    assert list_response.status_code == 200
    assert list_response.body[0]["job_id"] == create_response.body["job_id"]
    assert detail_response.status_code == 200
    assert detail_response.body["system_id"] == "crm"


def test_api_creates_and_lists_refresh_schedules():
    app = build_api()

    create_response = app.handle(
        "POST",
        "/api/v1/refresh-schedules",
        body={
            "systemId": "crm",
            "datasetProfileId": "profile-full-sanitized",
            "targetEnvironmentType": "dev",
            "intervalMinutes": 60,
            "createdBy": "steward@example.internal",
        },
    )
    list_response = app.handle("GET", "/api/v1/refresh-schedules")

    assert create_response.status_code == 202
    assert create_response.body["schedule_id"] == "refresh-schedule-1"
    assert create_response.body["status"] == "enabled"
    assert create_response.body["target_environment_type"] == "dev"

    assert list_response.status_code == 200
    assert list_response.body[0]["schedule_id"] == "refresh-schedule-1"
    assert list_response.body[0]["interval_minutes"] == 60


def test_api_exposes_baseline_and_publish_job_lineage():
    app = build_api()

    baseline_response = app.handle(
        "GET",
        "/api/v1/baselines/baseline-crm-dev-v1/lineage",
    )
    job_response = app.handle("GET", "/api/v1/jobs/job-1/lineage")

    assert baseline_response.status_code == 200
    assert baseline_response.body["subject_type"] == "sanitized_baseline"
    assert baseline_response.body["subject_id"] == "baseline-crm-dev-v1"
    assert baseline_response.body["items"][0]["event_type"] == "baseline_materialized"

    assert job_response.status_code == 200
    assert job_response.body["subject_type"] == "publish_job"
    assert job_response.body["subject_id"] == "job-1"
    assert job_response.body["items"][0]["event_type"] == "baseline_published"


def test_api_exposes_extraction_job_lineage():
    app = build_api()

    response = app.handle("GET", "/api/v1/extraction-jobs/extraction-1/lineage")

    assert response.status_code == 200
    assert response.body["subject_type"] == "extraction_job"
    assert response.body["subject_id"] == "extraction-1"
    assert [item["event_type"] for item in response.body["items"]] == [
        "extraction_from_source",
        "extraction_root_selected",
    ]
