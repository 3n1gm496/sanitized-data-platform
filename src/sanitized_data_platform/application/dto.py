from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sanitized_data_platform.domain.entities import (
    ArtifactPublishJob,
    AuditEvent,
    BaselineTableAsset,
    BaselineRefreshJob,
    ExtractionArtifact,
    BaselineRefreshSchedule,
    ExtractionJob,
    ExtractionPlan,
    ExtractionPlanSnapshot,
    LineageRecord,
    MetadataObject,
    PolicyCoverageGap,
    PolicyCoverageReport,
    PublishJob,
    Relationship,
    SanitizedBaseline,
    SensitivityTag,
    TransformationPolicy,
    ValidationCheckResult,
    ValidationReport,
)
from sanitized_data_platform.domain.enums import (
    BaselineRefreshStatus,
    DatabaseEngine,
    EnvironmentType,
    ValidationStatus,
)


@dataclass(frozen=True, slots=True)
class SystemSummary:
    system_id: str
    name: str
    source_engine: DatabaseEngine
    available_profiles: int


@dataclass(frozen=True, slots=True)
class SourceSummary:
    source_id: str
    system_id: str
    system_name: str
    engine_type: DatabaseEngine
    database_name: str
    access_mode: str


@dataclass(frozen=True, slots=True)
class EngineCapabilityView:
    engine_type: str
    metadata_discovery_supported: bool
    extraction_supported: bool
    artifact_publish_supported: bool
    baseline_refresh_supported: bool
    baseline_publish_supported: bool
    release_ready: bool


@dataclass(frozen=True, slots=True)
class EngineCapabilityListingView:
    items: list[EngineCapabilityView]


@dataclass(frozen=True, slots=True)
class CreatePublishJobCommand:
    source_id: str
    target_environment_id: str
    dataset_profile_id: str
    requested_by: str


@dataclass(frozen=True, slots=True)
class CreateArtifactPublishJobCommand:
    extraction_artifact_id: str
    target_environment_id: str
    requested_by: str


@dataclass(frozen=True, slots=True)
class CreateBaselineRefreshJobCommand:
    system_id: str
    dataset_profile_id: str
    target_environment_type: str
    requested_by: str
    trigger_type: str = "manual"
    refresh_schedule_id: str | None = None


@dataclass(frozen=True, slots=True)
class CreateRefreshScheduleCommand:
    system_id: str
    dataset_profile_id: str
    target_environment_type: str
    interval_minutes: int
    created_by: str


@dataclass(frozen=True, slots=True)
class PreviewExtractionPlanCommand:
    source_id: str
    root_object_id: str
    criteria: list[dict[str, str]]
    selected_columns: list[str] | None = None
    artifact_kind: str = "sample"
    include_related: bool = False
    max_depth: int = 1


@dataclass(frozen=True, slots=True)
class CreateExtractionJobCommand:
    source_id: str
    root_object_id: str
    criteria: list[dict[str, str]]
    include_related: bool
    max_depth: int
    requested_by: str
    selected_columns: list[str] | None = None
    artifact_kind: str = "sample"


@dataclass(frozen=True, slots=True)
class ValidationSummaryView:
    status: str
    warning_count: int
    error_count: int
    validated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ValidationCheckResultView:
    check_name: str
    severity: str
    passed: bool
    message: str | None

    @classmethod
    def from_result(
        cls,
        result: ValidationCheckResult,
    ) -> "ValidationCheckResultView":
        return cls(
            check_name=result.check_name,
            severity=result.severity.value,
            passed=result.passed,
            message=result.message,
        )


@dataclass(frozen=True, slots=True)
class ValidationReportDetailView:
    report_id: str
    baseline_id: str
    status: str
    warning_count: int
    error_count: int
    publish_eligible: bool
    created_at: datetime
    checks: list[ValidationCheckResultView]

    @classmethod
    def from_report(cls, report: ValidationReport) -> "ValidationReportDetailView":
        return cls(
            report_id=report.report_id,
            baseline_id=report.baseline_id,
            status=report.status.value,
            warning_count=report.warning_count,
            error_count=report.error_count,
            publish_eligible=report.is_publish_eligible,
            created_at=report.created_at,
            checks=[
                ValidationCheckResultView.from_result(check)
                for check in report.checks
            ],
        )


@dataclass(frozen=True, slots=True)
class BaselineRefreshJobView:
    job_id: str
    system_id: str
    dataset_profile_id: str
    target_environment_type: str
    requested_by: str
    trigger_type: str
    refresh_schedule_id: str | None
    status: str
    baseline_id: str | None
    created_at: datetime
    updated_at: datetime
    result_summary: dict[str, Any]

    @classmethod
    def from_job(cls, job: BaselineRefreshJob) -> "BaselineRefreshJobView":
        return cls(
            job_id=job.job_id,
            system_id=job.system_id,
            dataset_profile_id=job.dataset_profile_id,
            target_environment_type=job.target_environment_type.value,
            requested_by=job.requested_by,
            trigger_type=job.trigger_type,
            refresh_schedule_id=job.refresh_schedule_id,
            status=job.status.value,
            baseline_id=job.baseline_id,
            created_at=job.created_at,
            updated_at=job.updated_at,
            result_summary=dict(job.result_summary),
        )


@dataclass(frozen=True, slots=True)
class RefreshScheduleView:
    schedule_id: str
    system_id: str
    dataset_profile_id: str
    target_environment_type: str
    interval_minutes: int
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    next_run_at: datetime
    last_dispatched_at: datetime | None

    @classmethod
    def from_schedule(cls, schedule: BaselineRefreshSchedule) -> "RefreshScheduleView":
        return cls(
            schedule_id=schedule.schedule_id,
            system_id=schedule.system_id,
            dataset_profile_id=schedule.dataset_profile_id,
            target_environment_type=schedule.target_environment_type.value,
            interval_minutes=schedule.interval_minutes,
            status=schedule.status.value,
            created_by=schedule.created_by,
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
            next_run_at=schedule.next_run_at,
            last_dispatched_at=schedule.last_dispatched_at,
        )


@dataclass(frozen=True, slots=True)
class LineageRecordView:
    record_id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    event_type: str
    created_at: datetime
    details: dict[str, Any]

    @classmethod
    def from_record(cls, record: LineageRecord) -> "LineageRecordView":
        return cls(
            record_id=record.record_id,
            source_type=record.source_type,
            source_id=record.source_id,
            target_type=record.target_type,
            target_id=record.target_id,
            event_type=record.event_type,
            created_at=record.created_at,
            details=dict(record.details),
        )


@dataclass(frozen=True, slots=True)
class LineageView:
    subject_type: str
    subject_id: str
    items: list[LineageRecordView]


@dataclass(frozen=True, slots=True)
class AuditEventView:
    event_id: str
    event_type: str
    actor: str
    subject_type: str
    subject_id: str
    details: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_event(cls, event: AuditEvent) -> "AuditEventView":
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            actor=event.actor,
            subject_type=event.subject_type,
            subject_id=event.subject_id,
            details=dict(event.details),
            created_at=event.created_at,
        )


@dataclass(frozen=True, slots=True)
class JobView:
    job_id: str
    status: str
    source_id: str
    sanitized_baseline_id: str | None
    baseline_validation_summary: ValidationSummaryView | None
    target_environment_id: str
    dataset_profile_id: str
    requested_by: str
    created_at: datetime
    updated_at: datetime
    execution_summary: dict[str, Any]

    @classmethod
    def from_job(cls, job: PublishJob) -> "JobView":
        validation_summary = None
        if job.baseline_validation_status is not None:
            validation_summary = ValidationSummaryView(
                status=job.baseline_validation_status.value,
                warning_count=job.baseline_validation_warning_count,
                error_count=job.baseline_validation_error_count,
                validated_at=job.baseline_validated_at,
            )

        return cls(
            job_id=job.job_id,
            status=job.status.value,
            source_id=job.source_id,
            sanitized_baseline_id=job.sanitized_baseline_id,
            baseline_validation_summary=validation_summary,
            target_environment_id=job.target_environment_id,
            dataset_profile_id=job.dataset_profile_id,
            requested_by=job.requested_by,
            created_at=job.created_at,
            updated_at=job.updated_at,
            execution_summary=dict(job.execution_summary),
        )


@dataclass(frozen=True, slots=True)
class ArtifactPublishJobView:
    job_id: str
    extraction_artifact_id: str
    source_id: str
    root_object_id: str
    target_environment_id: str
    requested_by: str
    status: str
    created_at: datetime
    updated_at: datetime
    execution_summary: dict[str, Any]

    @classmethod
    def from_job(cls, job: ArtifactPublishJob) -> "ArtifactPublishJobView":
        return cls(
            job_id=job.job_id,
            extraction_artifact_id=job.extraction_artifact_id,
            source_id=job.source_id,
            root_object_id=job.root_object_id,
            target_environment_id=job.target_environment_id,
            requested_by=job.requested_by,
            status=job.status.value,
            created_at=job.created_at,
            updated_at=job.updated_at,
            execution_summary=dict(job.execution_summary),
        )


@dataclass(frozen=True, slots=True)
class MetadataObjectView:
    object_id: str
    object_type: str
    name: str
    qualified_name: str
    container_name: str | None
    logical_data_type: str | None
    parent_object_id: str | None

    @classmethod
    def from_metadata_object(cls, metadata_object: MetadataObject) -> "MetadataObjectView":
        return cls(
            object_id=metadata_object.object_id,
            object_type=metadata_object.object_type.value,
            name=metadata_object.name,
            qualified_name=metadata_object.qualified_name,
            container_name=metadata_object.container_name,
            logical_data_type=metadata_object.logical_data_type,
            parent_object_id=metadata_object.parent_object_id,
        )


@dataclass(frozen=True, slots=True)
class MetadataCatalogView:
    system_id: str
    system_name: str
    source_id: str
    items: list[MetadataObjectView]


@dataclass(frozen=True, slots=True)
class ExtractionPlanCriteriaView:
    field_name: str
    operator: str
    value: str


@dataclass(frozen=True, slots=True)
class ExtractionPlanPreviewView:
    source_id: str
    root_object_id: str
    criteria: list[ExtractionPlanCriteriaView]
    selected_columns: list[str]
    artifact_kind: str
    include_related: bool
    max_depth: int
    selected_object_ids: list[str]
    selected_relationship_ids: list[str]
    notes: list[str]

    @classmethod
    def from_plan(cls, plan: ExtractionPlan) -> "ExtractionPlanPreviewView":
        return cls(
            source_id=plan.source_id,
            root_object_id=plan.root.object_id,
            criteria=[
                ExtractionPlanCriteriaView(
                    field_name=item.field_name,
                    operator=item.operator,
                    value=item.value,
                )
                for item in plan.root.criteria
            ],
            selected_columns=list(plan.root.selected_columns),
            artifact_kind=plan.root.artifact_kind.value,
            include_related=plan.traversal_rule.include_related,
            max_depth=plan.traversal_rule.max_depth,
            selected_object_ids=list(plan.selected_object_ids),
            selected_relationship_ids=list(plan.selected_relationship_ids),
            notes=list(plan.notes),
        )


@dataclass(frozen=True, slots=True)
class ExtractionPlanSnapshotDetailView:
    snapshot_id: str
    source_id: str
    root_object_id: str
    criteria: list[ExtractionPlanCriteriaView]
    selected_columns: list[str]
    artifact_kind: str
    include_related: bool
    max_depth: int
    selected_object_ids: list[str]
    selected_relationship_ids: list[str]
    notes: list[str]
    created_at: datetime
    created_by: str

    @classmethod
    def from_snapshot(
        cls,
        snapshot: ExtractionPlanSnapshot,
    ) -> "ExtractionPlanSnapshotDetailView":
        return cls(
            snapshot_id=snapshot.snapshot_id,
            source_id=snapshot.source_id,
            root_object_id=snapshot.root.object_id,
            criteria=[
                ExtractionPlanCriteriaView(
                    field_name=item.field_name,
                    operator=item.operator,
                    value=item.value,
                )
                for item in snapshot.root.criteria
            ],
            selected_columns=list(snapshot.root.selected_columns),
            artifact_kind=snapshot.root.artifact_kind.value,
            include_related=snapshot.traversal_rule.include_related,
            max_depth=snapshot.traversal_rule.max_depth,
            selected_object_ids=list(snapshot.selected_object_ids),
            selected_relationship_ids=list(snapshot.selected_relationship_ids),
            notes=list(snapshot.notes),
            created_at=snapshot.created_at,
            created_by=snapshot.created_by,
        )


@dataclass(frozen=True, slots=True)
class ExtractionJobView:
    job_id: str
    source_id: str
    system_id: str
    plan_snapshot_id: str
    extraction_artifact_id: str | None
    root_object_id: str
    criteria: list[ExtractionPlanCriteriaView]
    include_related: bool
    max_depth: int
    requested_by: str
    status: str
    created_at: datetime
    updated_at: datetime
    execution_summary: dict[str, Any]

    @classmethod
    def from_job(cls, job: ExtractionJob) -> "ExtractionJobView":
        return cls(
            job_id=job.job_id,
            source_id=job.source_id,
            system_id=job.system_id,
            plan_snapshot_id=job.plan_snapshot_id,
            extraction_artifact_id=job.extraction_artifact_id,
            root_object_id=job.root_object_id,
            criteria=[
                ExtractionPlanCriteriaView(
                    field_name=item.field_name,
                    operator=item.operator,
                    value=item.value,
                )
                for item in job.criteria
            ],
            include_related=job.include_related,
            max_depth=job.max_depth,
            requested_by=job.requested_by,
            status=job.status.value,
            created_at=job.created_at,
            updated_at=job.updated_at,
            execution_summary=dict(job.execution_summary),
        )


@dataclass(frozen=True, slots=True)
class ExtractionArtifactView:
    artifact_id: str
    job_id: str
    source_id: str
    root_object_id: str
    kind: str
    artifact_format: str
    artifact_path: str
    row_count: int
    file_size_bytes: int | None
    checksum: str | None
    column_count: int | None
    status: str
    available: bool
    expires_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime

    @classmethod
    def from_artifact(cls, artifact: ExtractionArtifact) -> "ExtractionArtifactView":
        return cls(
            artifact_id=artifact.artifact_id,
            job_id=artifact.job_id,
            source_id=artifact.source_id,
            root_object_id=artifact.root_object_id,
            kind=artifact.kind.value,
            artifact_format=artifact.artifact_format.value,
            artifact_path=artifact.artifact_path,
            row_count=artifact.row_count,
            file_size_bytes=artifact.file_size_bytes,
            checksum=artifact.checksum,
            column_count=artifact.column_count,
            status=artifact.status.value,
            available=artifact.is_available,
            expires_at=artifact.expires_at,
            deleted_at=artifact.deleted_at,
            created_at=artifact.created_at,
        )


@dataclass(frozen=True, slots=True)
class RelationshipView:
    relationship_id: str
    source_object_id: str
    target_object_id: str
    relationship_type: str
    inferred: bool
    confidence: float | None
    active: bool

    @classmethod
    def from_relationship(cls, relationship: Relationship) -> "RelationshipView":
        return cls(
            relationship_id=relationship.relationship_id,
            source_object_id=relationship.source_object_id,
            target_object_id=relationship.target_object_id,
            relationship_type=relationship.relationship_type,
            inferred=relationship.inferred,
            confidence=relationship.confidence,
            active=relationship.active,
        )


@dataclass(frozen=True, slots=True)
class RelationshipListingView:
    system_id: str
    system_name: str
    source_id: str
    filters: dict[str, str]
    items: list[RelationshipView]


@dataclass(frozen=True, slots=True)
class ClassificationView:
    tag_id: str
    object_id: str
    tag_name: str
    classification_status: str
    assigned_by: str
    approved: bool
    active: bool

    @classmethod
    def from_tag(cls, tag: SensitivityTag) -> "ClassificationView":
        return cls(
            tag_id=tag.tag_id,
            object_id=tag.object_id,
            tag_name=tag.tag_name,
            classification_status=tag.classification_status.value,
            assigned_by=tag.assigned_by,
            approved=tag.approved,
            active=tag.active,
        )


@dataclass(frozen=True, slots=True)
class ClassificationListingView:
    system_id: str
    system_name: str
    source_id: str
    filters: dict[str, str]
    items: list[ClassificationView]


@dataclass(frozen=True, slots=True)
class GovernanceObjectSummaryView:
    object_id: str
    object_type: str
    qualified_name: str
    classification_status: str
    sensitivity_tags: list[str]
    policy_present: bool
    policy_types: list[str]
    coverage_state: str
    gap_types: list[str]


@dataclass(frozen=True, slots=True)
class GovernanceSummaryListingView:
    system_id: str
    system_name: str
    source_id: str
    items: list[GovernanceObjectSummaryView]


@dataclass(frozen=True, slots=True)
class TransformationPolicyView:
    policy_id: str
    system_id: str
    system_name: str
    object_name: str
    canonical_object_id: str | None
    legacy_object_name: str
    target_mode: str
    column_name: str
    sensitivity_tag: str
    transformation_type: str
    reversible: bool
    active: bool

    @classmethod
    def from_policy(cls, policy: TransformationPolicy) -> "TransformationPolicyView":
        return cls(
            policy_id=policy.policy_id,
            system_id=policy.system_id,
            system_name=policy.system_name,
            object_name=policy.object_name,
            canonical_object_id=policy.target.canonical_object_id,
            legacy_object_name=policy.target.legacy_object_name or "",
            target_mode=(
                "canonical"
                if policy.target.canonical_object_id is not None
                else "legacy_fallback"
            ),
            column_name=policy.column_name,
            sensitivity_tag=policy.sensitivity_tag,
            transformation_type=policy.transformation_type.value,
            reversible=policy.reversible,
            active=policy.active,
        )


@dataclass(frozen=True, slots=True)
class PolicyListingView:
    filters: dict[str, str]
    items: list[TransformationPolicyView]


@dataclass(frozen=True, slots=True)
class PolicyCoverageGapView:
    gap_type: str
    object_name: str
    severity: str
    message: str
    sensitivity_tags: list[str]

    @classmethod
    def from_gap(cls, gap: PolicyCoverageGap) -> "PolicyCoverageGapView":
        return cls(
            gap_type=gap.gap_type,
            object_name=gap.object_name,
            severity=gap.severity.value,
            message=gap.message,
            sensitivity_tags=list(gap.sensitivity_tags),
        )


@dataclass(frozen=True, slots=True)
class PolicyCoverageReportView:
    system_id: str
    system_name: str
    source_id: str
    publish_ready: bool
    evaluated_object_count: int
    covered_object_count: int
    blocking_gap_count: int
    informational_gap_count: int
    gaps: list[PolicyCoverageGapView]

    @classmethod
    def from_report(cls, report: PolicyCoverageReport) -> "PolicyCoverageReportView":
        return cls(
            system_id=report.system_id,
            system_name=report.system_name,
            source_id=report.source_id,
            publish_ready=report.is_publish_ready,
            evaluated_object_count=report.evaluated_object_count,
            covered_object_count=report.covered_object_count,
            blocking_gap_count=len(report.blocking_gaps),
            informational_gap_count=len(report.informational_gaps),
            gaps=[PolicyCoverageGapView.from_gap(gap) for gap in report.gaps],
        )


@dataclass(frozen=True, slots=True)
class BaselineValidationSummaryView:
    status: str
    warning_count: int
    error_count: int
    validated_at: datetime | None

    @classmethod
    def from_report(
        cls,
        report: ValidationReport | None,
    ) -> "BaselineValidationSummaryView | None":
        if report is None:
            return None
        return cls(
            status=report.status.value,
            warning_count=report.warning_count,
            error_count=report.error_count,
            validated_at=report.created_at,
        )


@dataclass(frozen=True, slots=True)
class BaselineEligibilityView:
    eligible: bool
    reason: str
    details: dict[str, str]


@dataclass(frozen=True, slots=True)
class BaselineListItemView:
    baseline_id: str
    system_id: str
    system_name: str
    source_id: str
    dataset_profile_id: str
    target_environment_type: str
    engine_type: str
    version: str
    status: str
    refreshed_at: datetime
    asset_count: int
    storage_ready: bool
    publish_eligible: bool
    eligibility: BaselineEligibilityView
    validation_summary: BaselineValidationSummaryView | None


@dataclass(frozen=True, slots=True)
class BaselineListingView:
    filters: dict[str, str]
    items: list[BaselineListItemView]


@dataclass(frozen=True, slots=True)
class BaselineDetailView:
    baseline_id: str
    system_id: str
    system_name: str
    source_id: str
    dataset_profile_id: str
    target_environment_type: str
    engine_type: str
    version: str
    status: str
    created_at: datetime
    refreshed_at: datetime
    active: bool
    asset_count: int
    storage_ready: bool
    publish_eligible: bool
    eligibility: BaselineEligibilityView
    validation_summary: BaselineValidationSummaryView | None

    @classmethod
    def from_baseline(
        cls,
        baseline: SanitizedBaseline,
        *,
        asset_count: int,
        storage_ready: bool,
        publish_eligible: bool,
        eligibility: BaselineEligibilityView,
        validation_summary: BaselineValidationSummaryView | None,
    ) -> "BaselineDetailView":
        return cls(
            baseline_id=baseline.baseline_id,
            system_id=baseline.system_id,
            system_name=baseline.system_name,
            source_id=baseline.source_id,
            dataset_profile_id=baseline.dataset_profile_id,
            target_environment_type=baseline.target_environment_type.value,
            engine_type=baseline.engine_type.value,
            version=baseline.version,
            status=baseline.status.value,
            created_at=baseline.created_at,
            refreshed_at=baseline.refreshed_at,
            active=baseline.active,
            asset_count=asset_count,
            storage_ready=storage_ready,
            publish_eligible=publish_eligible,
            eligibility=eligibility,
            validation_summary=validation_summary,
        )


@dataclass(frozen=True, slots=True)
class BaselineTableAssetView:
    asset_id: str
    baseline_id: str
    source_id: str
    root_object_id: str
    artifact_format: str
    artifact_path: str
    row_count: int
    created_at: datetime
    checksum: str | None
    column_count: int | None
    import_order: int

    @classmethod
    def from_asset(cls, asset: BaselineTableAsset) -> "BaselineTableAssetView":
        return cls(
            asset_id=asset.asset_id,
            baseline_id=asset.baseline_id,
            source_id=asset.source_id,
            root_object_id=asset.root_object_id,
            artifact_format=asset.artifact_format.value,
            artifact_path=asset.artifact_path,
            row_count=asset.row_count,
            created_at=asset.created_at,
            checksum=asset.checksum,
            column_count=asset.column_count,
            import_order=asset.import_order,
        )


@dataclass(frozen=True, slots=True)
class BaselineAssetListingView:
    baseline_id: str
    items: list[BaselineTableAssetView]
