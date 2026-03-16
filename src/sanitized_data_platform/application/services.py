from __future__ import annotations

from collections import deque
from datetime import timedelta
import hashlib

from sanitized_data_platform.domain.entities import (
    AuditEvent,
    BaselineRefreshJob,
    BaselineRefreshSchedule,
    DataSource,
    ExtractionArtifact,
    ExtractionJob,
    ExtractionPlan,
    ExtractionPlanSnapshot,
    ExtractionRoot,
    LineageRecord,
    MetadataObject,
    PolicyCoverageGap,
    PolicyCoverageReport,
    PublishJob,
    Relationship,
    SanitizedBaseline,
    SelectionCriteria,
    TransformationPolicy,
    TraversalRule,
    ValidationReport,
)
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.domain.enums import (
    BaselineRefreshStatus,
    BaselineStatus,
    ClassificationStatus,
    EnvironmentType,
    ExtractionArtifactStatus,
    ExtractionJobStatus,
    MetadataObjectType,
    PolicyCoverageSeverity,
    RefreshScheduleStatus,
    TransformationType,
)

from .dto import (
    BaselineDetailView,
    BaselineEligibilityView,
    BaselineListItemView,
    BaselineListingView,
    BaselineValidationSummaryView,
    BaselineRefreshJobView,
    ClassificationListingView,
    ClassificationView,
    CreateExtractionJobCommand,
    ExtractionArtifactView,
    GovernanceObjectSummaryView,
    ExtractionPlanSnapshotDetailView,
    GovernanceSummaryListingView,
    LineageRecordView,
    LineageView,
    CreateRefreshScheduleCommand,
    CreateBaselineRefreshJobCommand,
    CreatePublishJobCommand,
    PreviewExtractionPlanCommand,
    ExtractionPlanPreviewView,
    ExtractionJobView,
    JobView,
    MetadataCatalogView,
    MetadataObjectView,
    PolicyCoverageReportView,
    PolicyListingView,
    RelationshipListingView,
    RelationshipView,
    ValidationReportDetailView,
    SystemSummary,
    TransformationPolicyView,
    ValidationSummaryView,
    RefreshScheduleView,
)
from .ports import (
    AuditEventRepository,
    BaselineRepository,
    BaselineRefreshJobRepository,
    BaselineRefreshPipelinePort,
    BaselineRefreshQueuePort,
    BaselineRefreshScheduleRepository,
    ClassificationRepository,
    ClockPort,
    DataSourceRepository,
    DatasetProfileRepository,
    ExtractionArtifactRepository,
    ExtractionJobRepository,
    ExtractionPlanSnapshotRepository,
    ExtractionPipelinePort,
    ExtractionQueuePort,
    IdGeneratorPort,
    JobQueuePort,
    LineageRepository,
    MetadataCatalogRepository,
    PolicyPort,
    PublishJobRepository,
    SourceMetadataDiscoveryPort,
    SystemRepository,
    TargetEnvironmentRepository,
    TransformationPolicyRepository,
    ValidationRepository,
)


class CatalogQueryService:
    def __init__(
        self,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        environments: TargetEnvironmentRepository,
        dataset_profiles: DatasetProfileRepository,
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._environments = environments
        self._dataset_profiles = dataset_profiles

    def list_systems(self) -> list[SystemSummary]:
        active_profiles = self._dataset_profiles.list_active()
        summaries: list[SystemSummary] = []

        for system in self._systems.list_active():
            source = self._data_sources.get_active_by_system_id(system.system_id)
            if source is None:
                continue
            profile_count = sum(
                1
                for profile in active_profiles
                if profile.system_id == system.system_id
            )
            summaries.append(
                SystemSummary(
                    system_id=system.system_id,
                    name=system.name,
                    source_engine=source.engine_type,
                    available_profiles=profile_count,
                )
            )

        return summaries

    def list_environments(self):
        return self._environments.list_active()

    def list_dataset_profiles(
        self,
        *,
        source_id: str | None = None,
        target_environment_id: str | None = None,
    ):
        profiles = self._dataset_profiles.list_active()

        if source_id is None and target_environment_id is None:
            return profiles

        source = (
            self._data_sources.get_by_id(source_id) if source_id is not None else None
        )
        target = (
            self._environments.get_by_id(target_environment_id)
            if target_environment_id is not None
            else None
        )

        filtered = []
        for profile in profiles:
            if source is not None and profile.system_id != source.system_id:
                continue
            if (
                target is not None
                and profile.target_environment_type != target.environment_type
            ):
                continue
            filtered.append(profile)

        return filtered


class RowTransformationService:
    """Applies a minimal policy-driven transformation subset to extracted rows."""

    _MASK_VALUE = "***MASKED***"
    _ALPHA_LOWER = "abcdefghijklmnopqrstuvwxyz"
    _ALPHA_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    _DIGITS = "0123456789"
    _UNSUPPORTED = object()

    def apply_to_rows(
        self,
        *,
        object_id: str,
        object_name: str,
        rows: list[dict[str, object]],
        policies: list[TransformationPolicy],
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        matching_policies = {
            policy.column_name: policy
            for policy in policies
            if policy.active
            and self._policy_matches_target(
                policy=policy,
                object_id=object_id,
                object_name=object_name,
            )
        }
        if not rows or not matching_policies:
            return (
                [dict(row) for row in rows],
                {
                    "applied": False,
                    "transformedColumns": [],
                    "transformedValueCount": 0,
                    "unsupportedTransformationTypes": [],
                },
            )

        transformed_columns: set[str] = set()
        unsupported_types: set[str] = set()
        transformed_value_count = 0
        transformed_rows: list[dict[str, object]] = []

        for row in rows:
            next_row = dict(row)
            for column_name, policy in matching_policies.items():
                if column_name not in next_row:
                    continue
                current_value = next_row[column_name]
                transformed_value = self._transform_value(
                    value=current_value,
                    policy=policy,
                )
                if transformed_value is self._UNSUPPORTED:
                    unsupported_types.add(policy.transformation_type.value)
                    continue
                if transformed_value != current_value:
                    transformed_columns.add(column_name)
                    transformed_value_count += 1
                next_row[column_name] = transformed_value
            transformed_rows.append(next_row)

        return (
            transformed_rows,
            {
                "applied": transformed_value_count > 0,
                "transformedColumns": sorted(transformed_columns),
                "transformedValueCount": transformed_value_count,
                "unsupportedTransformationTypes": sorted(unsupported_types),
            },
        )

    def _transform_value(
        self,
        *,
        value: object,
        policy: TransformationPolicy,
    ) -> object:
        if policy.transformation_type == TransformationType.IRREVERSIBLE_MASKING:
            if value is None:
                return value
            return self._MASK_VALUE
        if policy.transformation_type == TransformationType.DETERMINISTIC_PSEUDONYMIZATION:
            if value is None:
                return value
            return self._pseudonymize_deterministically(value)
        if policy.transformation_type == TransformationType.HASHING:
            if value is None:
                return value
            return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
        return self._UNSUPPORTED

    def _policy_matches_target(
        self,
        *,
        policy: TransformationPolicy,
        object_id: str,
        object_name: str,
    ) -> bool:
        return policy.target.matches_table_identity(
            canonical_object_id=object_id,
            legacy_object_name=object_name,
        )

    def _pseudonymize_deterministically(self, value: object) -> str:
        text = str(value)
        if not text:
            return text
        seed = f"deterministic_pseudonymization:{text}"
        email_value = self._pseudonymize_email_like(text=text, seed=seed)
        if email_value is not None:
            return email_value
        return self._pseudonymize_with_shape(text=text, seed=seed)

    def _pseudonymize_email_like(self, *, text: str, seed: str) -> str | None:
        at_index = text.find("@")
        if at_index <= 0 or at_index != text.rfind("@"):
            return None
        local_part = text[:at_index]
        domain_part = text[at_index + 1 :]
        head, separator, suffix = domain_part.rpartition(".")
        if not separator or not head or not suffix:
            return None
        pseudo_local = self._pseudonymize_with_shape(
            text=local_part,
            seed=f"{seed}:local",
        )
        pseudo_head = self._pseudonymize_with_shape(
            text=head,
            seed=f"{seed}:domain",
        )
        return f"{pseudo_local}@{pseudo_head}.{suffix}"

    def _pseudonymize_with_shape(self, *, text: str, seed: str) -> str:
        transformed: list[str] = []
        for index, char in enumerate(text):
            charset = self._charset_for_char(char)
            if charset is None:
                transformed.append(char)
                continue
            slot = self._deterministic_index(seed=seed, position=index, modulo=len(charset))
            transformed.append(charset[slot])
        return "".join(transformed)

    def _charset_for_char(self, char: str) -> str | None:
        if char.islower():
            return self._ALPHA_LOWER
        if char.isupper():
            return self._ALPHA_UPPER
        if char.isdigit():
            return self._DIGITS
        return None

    @staticmethod
    def _deterministic_index(
        *,
        seed: str,
        position: int,
        modulo: int,
    ) -> int:
        digest = hashlib.sha256(f"{seed}:{position}".encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") % modulo


def resolve_active_source_for_system(
    systems: SystemRepository,
    data_sources: DataSourceRepository,
    system_id: str,
) -> DataSource:
    system = systems.get_by_id(system_id)
    if system is None or not system.active:
        raise DomainError(f"Unknown system: {system_id}")
    source = data_sources.get_active_by_system_id(system_id)
    if source is not None:
        return source
    raise DomainError(f"No active source configured for system: {system_id}")


def resolve_active_system(
    systems: SystemRepository,
    system_id: str,
):
    system = systems.get_by_id(system_id)
    if system is None or not system.active:
        raise DomainError(f"Unknown system: {system_id}")
    return system


class MetadataQueryService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        metadata_catalog: MetadataCatalogRepository,
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._metadata_catalog = metadata_catalog

    def list_metadata_objects(self, system_id: str) -> MetadataCatalogView:
        system = resolve_active_system(self._systems, system_id)
        source = resolve_active_source_for_system(
            self._systems,
            self._data_sources,
            system_id,
        )
        objects = [
            MetadataObjectView.from_metadata_object(item)
            for item in self._metadata_catalog.list_objects(source.source_id)
            if item.active
        ]
        return MetadataCatalogView(
            system_id=source.system_id,
            system_name=system.name,
            source_id=source.source_id,
            items=objects,
        )


class RelationshipQueryService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        metadata_catalog: MetadataCatalogRepository,
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._metadata_catalog = metadata_catalog

    def list_relationships(
        self,
        system_id: str,
        *,
        object_id: str | None = None,
        relationship_type: str | None = None,
    ) -> RelationshipListingView:
        system = resolve_active_system(self._systems, system_id)
        source = resolve_active_source_for_system(
            self._systems,
            self._data_sources,
            system_id,
        )
        relationships = [
            relationship
            for relationship in self._metadata_catalog.list_relationships(source.source_id)
            if relationship.active
        ]

        filters = {
            key: value
            for key, value in {
                "objectId": object_id,
                "relationshipType": relationship_type,
            }.items()
            if value is not None
        }

        if object_id is not None:
            relationships = [
                relationship
                for relationship in relationships
                if relationship.source_object_id == object_id
                or relationship.target_object_id == object_id
            ]
        if relationship_type is not None:
            relationships = [
                relationship
                for relationship in relationships
                if relationship.relationship_type == relationship_type
            ]

        return RelationshipListingView(
            system_id=source.system_id,
            system_name=system.name,
            source_id=source.source_id,
            filters=filters,
            items=[
                RelationshipView.from_relationship(relationship)
                for relationship in relationships
            ],
        )


class ClassificationQueryService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        classifications: ClassificationRepository,
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._classifications = classifications

    def list_classifications(
        self,
        system_id: str,
        *,
        object_id: str | None = None,
        classification_status: str | None = None,
        sensitivity_tag: str | None = None,
    ) -> ClassificationListingView:
        system = resolve_active_system(self._systems, system_id)
        source = resolve_active_source_for_system(
            self._systems,
            self._data_sources,
            system_id,
        )
        items = [
            tag
            for tag in self._classifications.list_sensitivity_tags(source.source_id)
            if tag.active
        ]

        filters = {
            key: value
            for key, value in {
                "objectId": object_id,
                "classificationStatus": classification_status,
                "sensitivityTag": sensitivity_tag,
            }.items()
            if value is not None
        }

        if object_id is not None:
            items = [tag for tag in items if tag.object_id == object_id]
        if classification_status is not None:
            items = [
                tag
                for tag in items
                if tag.classification_status.value == classification_status
            ]
        if sensitivity_tag is not None:
            items = [tag for tag in items if tag.tag_name == sensitivity_tag]

        return ClassificationListingView(
            system_id=source.system_id,
            system_name=system.name,
            source_id=source.source_id,
            filters=filters,
            items=[ClassificationView.from_tag(tag) for tag in items],
        )


class GovernanceSummaryQueryService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        metadata_catalog: MetadataCatalogRepository,
        classifications: ClassificationRepository,
        policies: TransformationPolicyRepository,
        coverage: "PolicyCoverageEvaluationService",
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._metadata_catalog = metadata_catalog
        self._classifications = classifications
        self._policies = policies
        self._coverage = coverage

    def list_governance_summary(self, system_id: str) -> GovernanceSummaryListingView:
        system = resolve_active_system(self._systems, system_id)
        source = resolve_active_source_for_system(
            self._systems,
            self._data_sources,
            system_id,
        )
        report = self._coverage.evaluate_for_source(source)
        gaps_by_object_id: dict[str, list[PolicyCoverageGap]] = {}
        for gap in report.gaps:
            gaps_by_object_id.setdefault(gap.metadata_object_id, []).append(gap)

        tags_by_object_id: dict[str, list] = {}
        for tag in self._classifications.list_sensitivity_tags(source.source_id):
            if not tag.active:
                continue
            tags_by_object_id.setdefault(tag.object_id, []).append(tag)

        policies = self._policies.list_active_for_system(source.system_id)
        items: list[GovernanceObjectSummaryView] = []
        for metadata_object in self._metadata_catalog.list_objects(source.source_id):
            if not metadata_object.active:
                continue
            tags = tags_by_object_id.get(metadata_object.object_id, [])
            matching_policies = [
                policy
                for policy in policies
                if policy.active and policy.applies_to(metadata_object, tags)
            ]
            object_gap_types = [
                gap.gap_type
                for gap in gaps_by_object_id.get(metadata_object.object_id, [])
            ]
            items.append(
                GovernanceObjectSummaryView(
                    object_id=metadata_object.object_id,
                    object_type=metadata_object.object_type.value,
                    qualified_name=metadata_object.qualified_name,
                    classification_status=self._classification_status_for_object(
                        metadata_object=metadata_object,
                        tags=tags,
                    ),
                    sensitivity_tags=sorted(
                        {
                            tag.tag_name
                            for tag in tags
                            if tag.classification_status != ClassificationStatus.NON_SENSITIVE
                        }
                    ),
                    policy_present=bool(matching_policies),
                    policy_types=sorted(
                        {
                            policy.transformation_type.value
                            for policy in matching_policies
                        }
                    ),
                    coverage_state=self._coverage_state_for_object(
                        metadata_object=metadata_object,
                        gap_types=object_gap_types,
                    ),
                    gap_types=object_gap_types,
                )
            )

        return GovernanceSummaryListingView(
            system_id=source.system_id,
            system_name=system.name,
            source_id=source.source_id,
            items=items,
        )

    @staticmethod
    def _classification_status_for_object(
        *,
        metadata_object: MetadataObject,
        tags: list,
    ) -> str:
        if not metadata_object.is_column:
            return "not_applicable"
        if not tags:
            return "unclassified"
        if any(tag.needs_review for tag in tags):
            return "needs_review"
        if any(tag.is_sensitive for tag in tags):
            return "sensitive"
        if any(tag.is_non_sensitive for tag in tags):
            return "non_sensitive"
        return "unclassified"

    @staticmethod
    def _coverage_state_for_object(
        *,
        metadata_object: MetadataObject,
        gap_types: list[str],
    ) -> str:
        if not metadata_object.is_column:
            return "not_applicable"
        if not gap_types:
            return "complete"
        if any(
            gap_type in {
                "classification_needs_review",
                "missing_transformation_policy",
                "linked_classification_mismatch",
                "linked_policy_mismatch",
                "linked_sensitive_handling_inconsistent",
            }
            for gap_type in gap_types
        ):
            return "blocking_gap"
        return "informational_gap"


class ExtractionPlanningService:
    def __init__(self, metadata_catalog: MetadataCatalogRepository) -> None:
        self._metadata_catalog = metadata_catalog

    def build_plan(
        self,
        *,
        source_id: str,
        root_object_id: str,
        criteria: list[SelectionCriteria] | None = None,
        selected_columns: list[str] | None = None,
        include_related: bool = False,
        max_depth: int = 1,
    ) -> ExtractionPlan:
        objects = [
            item
            for item in self._metadata_catalog.list_objects(source_id)
            if item.active
        ]
        object_by_id = {item.object_id: item for item in objects}
        root_object = object_by_id.get(root_object_id)
        if root_object is None:
            raise DomainError(f"Unknown metadata object for extraction planning: {root_object_id}")
        validated_selected_columns = self._validate_selected_columns(
            root_object=root_object,
            objects=objects,
            selected_columns=selected_columns or [],
        )

        relationships = [
            relationship
            for relationship in self._metadata_catalog.list_relationships(source_id)
            if relationship.active and relationship.relationship_type == "foreign_key"
        ]
        traversal_rule = TraversalRule(
            include_related=include_related,
            max_depth=(max_depth if include_related else 0),
        )
        selected_object_ids = {root_object.object_id}
        selected_relationship_ids: set[str] = set()
        notes = []
        if include_related:
            table_neighbors = self._build_table_neighbors(relationships, object_by_id)
            self._expand_related_tables(
                root_object=root_object,
                table_neighbors=table_neighbors,
                selected_object_ids=selected_object_ids,
                selected_relationship_ids=selected_relationship_ids,
                max_depth=max_depth,
            )
            if not selected_relationship_ids:
                notes.append("No active foreign-key relationships expanded from the selected root.")

        return ExtractionPlan(
            source_id=source_id,
            root=ExtractionRoot(
                object_id=root_object_id,
                criteria=tuple(criteria or ()),
                selected_columns=tuple(validated_selected_columns),
            ),
            traversal_rule=traversal_rule,
            selected_object_ids=tuple(sorted(selected_object_ids)),
            selected_relationship_ids=tuple(sorted(selected_relationship_ids)),
            notes=tuple(notes),
        )

    def _build_table_neighbors(
        self,
        relationships: list[Relationship],
        object_by_id: dict[str, MetadataObject],
    ) -> dict[str, list[tuple[str, str]]]:
        neighbors: dict[str, list[tuple[str, str]]] = {}
        for relationship in relationships:
            source_column = object_by_id.get(relationship.source_object_id)
            target_column = object_by_id.get(relationship.target_object_id)
            if source_column is None or target_column is None:
                continue
            if source_column.parent_object_id is None or target_column.parent_object_id is None:
                continue
            source_table_id = source_column.parent_object_id
            target_table_id = target_column.parent_object_id
            neighbors.setdefault(source_table_id, []).append(
                (target_table_id, relationship.relationship_id)
            )
            neighbors.setdefault(target_table_id, []).append(
                (source_table_id, relationship.relationship_id)
            )
        return neighbors

    def _expand_related_tables(
        self,
        *,
        root_object: MetadataObject,
        table_neighbors: dict[str, list[tuple[str, str]]],
        selected_object_ids: set[str],
        selected_relationship_ids: set[str],
        max_depth: int,
    ) -> None:
        if max_depth <= 0:
            return
        root_table_id = (
            root_object.object_id
            if root_object.object_type == MetadataObjectType.TABLE
            else root_object.parent_object_id
        )
        if root_table_id is None:
            return

        queue: deque[tuple[str, int]] = deque([(root_table_id, 0)])
        visited = {root_table_id}
        while queue:
            table_id, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor_table_id, relationship_id in table_neighbors.get(table_id, []):
                selected_relationship_ids.add(relationship_id)
                if neighbor_table_id in visited:
                    continue
                visited.add(neighbor_table_id)
                selected_object_ids.add(neighbor_table_id)
                queue.append((neighbor_table_id, depth + 1))

    def _validate_selected_columns(
        self,
        *,
        root_object: MetadataObject,
        objects: list[MetadataObject],
        selected_columns: list[str],
    ) -> list[str]:
        if not selected_columns:
            return []
        if root_object.object_type != MetadataObjectType.TABLE:
            raise DomainError(
                "Selected columns are currently supported only for table-root extraction plans."
            )

        known_columns = {
            item.name
            for item in objects
            if item.active
            and item.object_type == MetadataObjectType.COLUMN
            and item.parent_object_id == root_object.object_id
        }
        validated: list[str] = []
        seen: set[str] = set()
        for column_name in selected_columns:
            if column_name in seen:
                continue
            if column_name not in known_columns:
                raise DomainError(
                    f"Unknown selected column for extraction root {root_object.object_id}: {column_name}"
                )
            seen.add(column_name)
            validated.append(column_name)
        return validated


class ExtractionPlanPreviewService:
    def __init__(self, planning: ExtractionPlanningService) -> None:
        self._planning = planning

    def preview_plan(
        self,
        command: PreviewExtractionPlanCommand,
    ) -> ExtractionPlanPreviewView:
        criteria = [
            SelectionCriteria(
                field_name=item["fieldName"],
                operator=item["operator"],
                value=item["value"],
            )
            for item in command.criteria
        ]
        plan = self._planning.build_plan(
            source_id=command.source_id,
            root_object_id=command.root_object_id,
            criteria=criteria,
            selected_columns=command.selected_columns,
            include_related=command.include_related,
            max_depth=command.max_depth,
        )
        return ExtractionPlanPreviewView.from_plan(plan)


class ExtractionJobRequestService:
    def __init__(
        self,
        *,
        data_sources: DataSourceRepository,
        extraction_jobs: ExtractionJobRepository,
        extraction_plan_snapshots: ExtractionPlanSnapshotRepository,
        extraction_queue: ExtractionQueuePort,
        planning: ExtractionPlanningService,
        audits: AuditEventRepository,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._data_sources = data_sources
        self._extraction_jobs = extraction_jobs
        self._extraction_plan_snapshots = extraction_plan_snapshots
        self._extraction_queue = extraction_queue
        self._planning = planning
        self._audits = audits
        self._clock = clock
        self._ids = ids

    def create_job(self, command: CreateExtractionJobCommand) -> ExtractionJobView:
        source = self._data_sources.get_by_id(command.source_id)
        if source is None or not source.active:
            raise DomainError(f"Unknown or inactive data source: {command.source_id}")

        criteria = tuple(
            SelectionCriteria(
                field_name=item["fieldName"],
                operator=item["operator"],
                value=item["value"],
            )
            for item in command.criteria
        )
        plan = self._planning.build_plan(
            source_id=command.source_id,
            root_object_id=command.root_object_id,
            criteria=list(criteria),
            selected_columns=command.selected_columns,
            include_related=command.include_related,
            max_depth=command.max_depth,
        )

        now = self._clock.now()
        plan_snapshot = ExtractionPlanSnapshot.from_plan(
            snapshot_id=self._ids.new_id("extraction-plan-snapshot"),
            plan=plan,
            created_at=now,
            created_by=command.requested_by,
        )
        self._extraction_plan_snapshots.add(plan_snapshot)
        job = ExtractionJob.create(
            job_id=self._ids.new_id("extraction"),
            source_id=command.source_id,
            system_id=source.system_id,
            plan_snapshot_id=plan_snapshot.snapshot_id,
            root_object_id=command.root_object_id,
            criteria=criteria,
            include_related=command.include_related,
            max_depth=command.max_depth,
            requested_by=command.requested_by,
            created_at=now,
        )
        self._extraction_jobs.add(job)
        self._extraction_queue.enqueue(job.job_id)
        self._audits.add(
            AuditEvent(
                event_id=self._ids.new_id("audit"),
                event_type="extraction_job_requested",
                actor=command.requested_by,
                subject_type="extraction_job",
                subject_id=job.job_id,
                details={
                    "sourceId": command.source_id,
                    "rootObjectId": command.root_object_id,
                    "selectedColumnCount": len(plan.root.selected_columns),
                    "planSnapshotId": plan_snapshot.snapshot_id,
                    "selectedObjectCount": len(plan.selected_object_ids),
                    "selectedRelationshipCount": len(plan.selected_relationship_ids),
                },
                created_at=now,
            )
        )
        return ExtractionJobView.from_job(job)


class ExtractionJobMonitoringService:
    def __init__(self, extraction_jobs: ExtractionJobRepository) -> None:
        self._extraction_jobs = extraction_jobs

    def list_jobs(self) -> list[ExtractionJobView]:
        jobs = sorted(
            self._extraction_jobs.list_all(),
            key=lambda job: job.created_at,
            reverse=True,
        )
        return [ExtractionJobView.from_job(job) for job in jobs]

    def get_job(self, job_id: str) -> ExtractionJobView:
        job = self._extraction_jobs.get_by_id(job_id)
        if job is None:
            raise DomainError(f"Unknown extraction job: {job_id}")
        return ExtractionJobView.from_job(job)


class ExtractionPlanSnapshotQueryService:
    def __init__(
        self,
        snapshots: ExtractionPlanSnapshotRepository,
    ) -> None:
        self._snapshots = snapshots

    def get_snapshot(self, snapshot_id: str) -> ExtractionPlanSnapshotDetailView:
        snapshot = self._snapshots.get_by_id(snapshot_id)
        if snapshot is None:
            raise DomainError(f"Unknown extraction plan snapshot: {snapshot_id}")
        return ExtractionPlanSnapshotDetailView.from_snapshot(snapshot)


class ExtractionArtifactQueryService:
    def __init__(
        self,
        *,
        jobs: ExtractionJobRepository,
        artifacts: ExtractionArtifactRepository,
        lifecycle: "ExtractionArtifactLifecycleService",
    ) -> None:
        self._jobs = jobs
        self._artifacts = artifacts
        self._lifecycle = lifecycle

    def get_artifact_for_job(self, job_id: str) -> ExtractionArtifactView:
        job = self._jobs.get_by_id(job_id)
        if job is None:
            raise DomainError(f"Unknown extraction job: {job_id}")

        artifact = (
            None
            if job.extraction_artifact_id is None
            else self._artifacts.get_by_id(job.extraction_artifact_id)
        )
        if artifact is None:
            artifact = self._artifacts.get_by_job_id(job_id)
        if artifact is None:
            raise DomainError(f"No extraction artifact available for job: {job_id}")
        artifact = self._lifecycle.evaluate_availability(artifact)
        return ExtractionArtifactView.from_artifact(artifact)


class ExtractionArtifactLifecycleService:
    def __init__(
        self,
        *,
        artifacts: ExtractionArtifactRepository,
        clock: ClockPort,
        default_retention: timedelta = timedelta(hours=24),
    ) -> None:
        self._artifacts = artifacts
        self._clock = clock
        self._default_retention = default_retention

    def attach_default_expiration(self, artifact: ExtractionArtifact) -> ExtractionArtifact:
        if artifact.expires_at is not None:
            return artifact
        return ExtractionArtifact(
            artifact_id=artifact.artifact_id,
            job_id=artifact.job_id,
            source_id=artifact.source_id,
            root_object_id=artifact.root_object_id,
            kind=artifact.kind,
            artifact_format=artifact.artifact_format,
            artifact_path=artifact.artifact_path,
            row_count=artifact.row_count,
            created_at=artifact.created_at,
            file_size_bytes=artifact.file_size_bytes,
            checksum=artifact.checksum,
            column_count=artifact.column_count,
            status=artifact.status,
            expires_at=artifact.created_at + self._default_retention,
            deleted_at=artifact.deleted_at,
        )

    def evaluate_availability(self, artifact: ExtractionArtifact) -> ExtractionArtifact:
        if (
            artifact.status == ExtractionArtifactStatus.AVAILABLE
            and artifact.expires_at is not None
            and artifact.expires_at <= self._clock.now()
        ):
            expired = artifact.expire(expired_at=artifact.expires_at)
            self._artifacts.save(expired)
            return expired
        return artifact

    def expire_due_artifacts(self) -> int:
        expired_count = 0
        now = self._clock.now()
        for artifact in self._artifacts.list_all():
            if (
                artifact.status == ExtractionArtifactStatus.AVAILABLE
                and artifact.expires_at is not None
                and artifact.expires_at <= now
            ):
                self._artifacts.save(artifact.expire(expired_at=artifact.expires_at))
                expired_count += 1
        return expired_count


class MetadataDiscoveryService:
    def __init__(
        self,
        *,
        data_sources: DataSourceRepository,
        discovery: SourceMetadataDiscoveryPort,
    ) -> None:
        self._data_sources = data_sources
        self._discovery = discovery

    def discover_metadata_objects(self, source_id: str) -> MetadataCatalogView:
        source = self._data_sources.get_by_id(source_id)
        if source is None or not source.active:
            raise DomainError(f"Unknown or inactive data source: {source_id}")

        objects = [
            *self._discovery.list_schemas(source),
            *self._discovery.list_tables(source),
            *self._discovery.list_columns(source),
        ]
        return MetadataCatalogView(
            system_id=source.system_id,
            system_name=source.system_name,
            source_id=source.source_id,
            items=[MetadataObjectView.from_metadata_object(item) for item in objects],
        )


class MetadataIngestionService:
    def __init__(
        self,
        *,
        data_sources: DataSourceRepository,
        discovery: SourceMetadataDiscoveryPort,
        metadata_catalog: MetadataCatalogRepository,
    ) -> None:
        self._data_sources = data_sources
        self._discovery = discovery
        self._metadata_catalog = metadata_catalog

    def ingest_discovered_metadata(self, source_id: str) -> MetadataCatalogView:
        source = self._require_active_source(source_id)
        discovered_objects = [
            *self._discovery.list_schemas(source),
            *self._discovery.list_tables(source),
            *self._discovery.list_columns(source),
        ]
        discovered_relationships = self._discovery.list_relationships(source)
        self._metadata_catalog.upsert_objects(discovered_objects)
        self._metadata_catalog.upsert_relationships(discovered_relationships)
        return MetadataCatalogView(
            system_id=source.system_id,
            system_name=source.system_name,
            source_id=source.source_id,
            items=[
                MetadataObjectView.from_metadata_object(item)
                for item in self._metadata_catalog.list_objects(source.source_id)
                if item.active
            ],
        )

    def _require_active_source(self, source_id: str) -> DataSource:
        source = self._data_sources.get_by_id(source_id)
        if source is None or not source.active:
            raise DomainError(f"Unknown or inactive data source: {source_id}")
        return source

    def list_ingested_relationships(self, source_id: str) -> list[Relationship]:
        source = self._require_active_source(source_id)
        return self._metadata_catalog.list_relationships(source.source_id)


class PolicyQueryService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        policies: TransformationPolicyRepository,
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._policies = policies

    def list_transformation_policies(
        self,
        *,
        system_id: str | None = None,
        object_name: str | None = None,
        column_name: str | None = None,
        target_mode: str | None = None,
    ) -> PolicyListingView:
        filters = {
            key: value
            for key, value in {
                "systemId": system_id,
                "objectName": object_name,
                "columnName": column_name,
                "targetMode": target_mode,
            }.items()
            if value is not None
        }

        if system_id is None:
            policies = []
            for system in self._systems.list_active():
                policies.extend(self._policies.list_active_for_system(system.system_id))
        else:
            resolve_active_system(self._systems, system_id)
            policies = self._policies.list_active_for_system(system_id)

        if object_name is not None:
            policies = [policy for policy in policies if policy.object_name == object_name]
        if column_name is not None:
            policies = [policy for policy in policies if policy.column_name == column_name]
        if target_mode is not None:
            policies = [
                policy
                for policy in policies
                if (
                    target_mode == "canonical"
                    and policy.target.canonical_object_id is not None
                )
                or (
                    target_mode == "legacy_fallback"
                    and policy.target.canonical_object_id is None
                )
            ]

        return PolicyListingView(
            filters=filters,
            items=[TransformationPolicyView.from_policy(policy) for policy in policies],
        )


class PolicyCoverageEvaluationService:
    def __init__(
        self,
        *,
        metadata_catalog: MetadataCatalogRepository,
        policies: TransformationPolicyRepository,
        classifications: ClassificationRepository,
        clock: ClockPort,
    ) -> None:
        self._metadata_catalog = metadata_catalog
        self._policies = policies
        self._classifications = classifications
        self._clock = clock

    def evaluate_for_source(self, source: DataSource) -> PolicyCoverageReport:
        columns = [
            item
            for item in self._metadata_catalog.list_objects(
                source.source_id,
                object_type=MetadataObjectType.COLUMN,
            )
            if item.active
        ]
        relationships = [
            relationship
            for relationship in self._metadata_catalog.list_relationships(source.source_id)
            if relationship.active and relationship.relationship_type == "foreign_key"
        ]
        columns_by_id = {column.object_id: column for column in columns}
        tags_by_object_id: dict[str, list] = {}
        for tag in self._classifications.list_sensitivity_tags(source.source_id):
            if not tag.active:
                continue
            tags_by_object_id.setdefault(tag.object_id, []).append(tag)

        policies = self._policies.list_active_for_system(source.system_id)
        gaps: list[PolicyCoverageGap] = []
        covered_object_count = 0
        column_states: dict[str, dict[str, object]] = {}

        for column in columns:
            tags = tags_by_object_id.get(column.object_id, [])
            state, matching_policy, gap = self._evaluate_column_governance(
                column=column,
                tags=tags,
                policies=policies,
            )
            column_states[column.object_id] = {
                "state": state,
                "policy": matching_policy,
            }
            if gap is not None:
                gaps.append(gap)
                continue
            if state in {"non_sensitive", "sensitive_with_policy"}:
                covered_object_count += 1

        gaps.extend(
            self._evaluate_relationship_governance(
                relationships=relationships,
                columns_by_id=columns_by_id,
                column_states=column_states,
            )
        )

        return PolicyCoverageReport(
            source_id=source.source_id,
            system_id=source.system_id,
            system_name=source.system_name,
            evaluated_object_count=len(columns),
            covered_object_count=covered_object_count,
            gaps=tuple(gaps),
            evaluated_at=self._clock.now(),
        )

    def _evaluate_column_governance(
        self,
        *,
        column: MetadataObject,
        tags: list,
        policies: list[TransformationPolicy],
    ) -> tuple[str, TransformationPolicy | None, PolicyCoverageGap | None]:
        if not tags:
            return (
                "unclassified",
                None,
                PolicyCoverageGap(
                    gap_type="missing_classification",
                    metadata_object_id=column.object_id,
                    object_name=column.qualified_name,
                    message="Column has no approved sensitivity classification yet.",
                    severity=PolicyCoverageSeverity.INFORMATIONAL,
                ),
            )

        if any(tag.needs_review for tag in tags):
            return (
                "needs_review",
                None,
                PolicyCoverageGap(
                    gap_type="classification_needs_review",
                    metadata_object_id=column.object_id,
                    object_name=column.qualified_name,
                    message="Column classification exists but still needs review.",
                    severity=PolicyCoverageSeverity.BLOCKING,
                    sensitivity_tags=tuple(tag.tag_name for tag in tags),
                ),
            )

        sensitive_tags = [tag for tag in tags if tag.is_sensitive]
        if not sensitive_tags and any(tag.is_non_sensitive for tag in tags):
            return "non_sensitive", None, None

        matching_policy = next(
            (
                policy
                for policy in policies
                if policy.active and policy.applies_to(column, sensitive_tags)
            ),
            None,
        )
        if matching_policy is not None:
            return "sensitive_with_policy", matching_policy, None

        return (
            "sensitive_without_policy",
            None,
            PolicyCoverageGap(
                gap_type="missing_transformation_policy",
                metadata_object_id=column.object_id,
                object_name=column.qualified_name,
                message="Sensitive column has no matching transformation policy.",
                severity=PolicyCoverageSeverity.BLOCKING,
                sensitivity_tags=tuple(tag.tag_name for tag in sensitive_tags),
            ),
        )

    def _evaluate_relationship_governance(
        self,
        *,
        relationships: list[Relationship],
        columns_by_id: dict[str, MetadataObject],
        column_states: dict[str, dict[str, object]],
    ) -> list[PolicyCoverageGap]:
        gaps: list[PolicyCoverageGap] = []

        for relationship in relationships:
            source_column = columns_by_id.get(relationship.source_object_id)
            target_column = columns_by_id.get(relationship.target_object_id)
            source_state = column_states.get(relationship.source_object_id)
            target_state = column_states.get(relationship.target_object_id)
            if (
                source_column is None
                or target_column is None
                or source_state is None
                or target_state is None
            ):
                continue

            source_classification = str(source_state["state"])
            target_classification = str(target_state["state"])
            if "needs_review" in {source_classification, target_classification}:
                continue

            relationship_name = (
                f"{source_column.qualified_name} -> {target_column.qualified_name}"
            )
            if {source_classification, target_classification} == {
                "sensitive_with_policy",
                "non_sensitive",
            } or {source_classification, target_classification} == {
                "sensitive_without_policy",
                "non_sensitive",
            }:
                gaps.append(
                    PolicyCoverageGap(
                        gap_type="linked_classification_mismatch",
                        metadata_object_id=relationship.source_object_id,
                        object_name=relationship_name,
                        message="Linked fields have inconsistent sensitive/non-sensitive classifications.",
                        severity=PolicyCoverageSeverity.BLOCKING,
                    )
                )
                continue

            if {source_classification, target_classification} in (
                {"sensitive_with_policy", "unclassified"},
                {"sensitive_without_policy", "unclassified"},
            ):
                gaps.append(
                    PolicyCoverageGap(
                        gap_type="linked_sensitive_handling_inconsistent",
                        metadata_object_id=relationship.source_object_id,
                        object_name=relationship_name,
                        message="A sensitive linked field is connected to a field without consistent classification or handling.",
                        severity=PolicyCoverageSeverity.BLOCKING,
                    )
                )
                continue

            if {
                source_classification,
                target_classification,
            } == {"sensitive_with_policy", "sensitive_without_policy"}:
                gaps.append(
                    PolicyCoverageGap(
                        gap_type="linked_sensitive_handling_inconsistent",
                        metadata_object_id=relationship.source_object_id,
                        object_name=relationship_name,
                        message="Linked sensitive fields do not have consistent policy handling.",
                        severity=PolicyCoverageSeverity.BLOCKING,
                    )
                )
                continue

            if source_classification == target_classification == "sensitive_with_policy":
                source_policy = source_state["policy"]
                target_policy = target_state["policy"]
                if not self._policies_are_consistent(source_policy, target_policy):
                    gaps.append(
                        PolicyCoverageGap(
                            gap_type="linked_policy_mismatch",
                            metadata_object_id=relationship.source_object_id,
                            object_name=relationship_name,
                            message="Linked sensitive fields have inconsistent transformation policies.",
                            severity=PolicyCoverageSeverity.BLOCKING,
                        )
                    )

        return gaps

    @staticmethod
    def _policies_are_consistent(
        source_policy: object | None,
        target_policy: object | None,
    ) -> bool:
        if source_policy is None or target_policy is None:
            return False
        return (
            source_policy.transformation_type == target_policy.transformation_type
            and source_policy.reversible == target_policy.reversible
        )


class PublishReadinessValidationService:
    def __init__(self, coverage: PolicyCoverageEvaluationService) -> None:
        self._coverage = coverage

    def assert_publish_ready(self, source: DataSource) -> PolicyCoverageReport:
        report = self._coverage.evaluate_for_source(source)
        if report.blocking_gaps:
            object_names = ", ".join(gap.object_name for gap in report.blocking_gaps[:3])
            raise DomainError(
                "Publish readiness failed because blocking policy coverage gaps exist"
                f" for: {object_names}."
            )
        return report


class BaselineLookupService:
    def __init__(self, baselines: BaselineRepository) -> None:
        self._baselines = baselines

    def list_active_for_system(self, system_id: str) -> list[SanitizedBaseline]:
        return [
            baseline
            for baseline in self._baselines.list_active_for_system(system_id)
            if baseline.is_selectable
        ]


class ValidationLookupService:
    def __init__(self, validations: ValidationRepository) -> None:
        self._validations = validations

    def get_latest_for_baseline(self, baseline_id: str) -> ValidationReport | None:
        return self._validations.get_latest_for_baseline(baseline_id)


class ValidationQueryService:
    def __init__(
        self,
        *,
        baselines: BaselineRepository,
        validations: ValidationLookupService,
    ) -> None:
        self._baselines = baselines
        self._validations = validations

    def get_validation_report_for_baseline(
        self,
        baseline_id: str,
    ) -> ValidationReportDetailView:
        baseline = self._baselines.get_by_id(baseline_id)
        if baseline is None:
            raise DomainError(f"Unknown sanitized baseline: {baseline_id}")
        report = self._validations.get_latest_for_baseline(baseline_id)
        if report is None:
            raise DomainError(f"No validation report is available for baseline: {baseline_id}")
        return ValidationReportDetailView.from_report(report)


class BaselineValidationEligibilityService:
    def __init__(self, validations: ValidationLookupService) -> None:
        self._validations = validations

    def require_publish_eligible(self, baseline: SanitizedBaseline) -> ValidationReport:
        report = self._validations.get_latest_for_baseline(baseline.baseline_id)
        if report is None:
            raise DomainError(
                "No validation report is available for the selected sanitized baseline."
            )
        if not report.is_publish_eligible:
            raise DomainError(
                "The selected sanitized baseline is not sufficiently validated for publish."
            )
        return report


class PublishValidationSummaryService:
    def summarize(self, report: ValidationReport | None) -> ValidationSummaryView | None:
        if report is None:
            return None
        return ValidationSummaryView(
            status=report.status.value,
            warning_count=report.warning_count,
            error_count=report.error_count,
            validated_at=report.created_at,
        )

    def summarize_baseline(
        self,
        report: ValidationReport | None,
    ) -> BaselineValidationSummaryView | None:
        return BaselineValidationSummaryView.from_report(report)


class BaselineEligibilityExplanationService:
    def explain(
        self,
        baseline: SanitizedBaseline,
        report: ValidationReport | None,
        *,
        compatibility_mismatch: bool = False,
    ) -> BaselineEligibilityView:
        if compatibility_mismatch:
            return BaselineEligibilityView(
                eligible=False,
                reason="compatibility_mismatch",
                details={
                    "baselineId": baseline.baseline_id,
                    "systemId": baseline.system_id,
                },
            )

        if not baseline.active or not baseline.is_selectable:
            return BaselineEligibilityView(
                eligible=False,
                reason="baseline_not_active",
                details={
                    "baselineId": baseline.baseline_id,
                    "baselineStatus": baseline.status.value,
                },
            )

        if report is None:
            return BaselineEligibilityView(
                eligible=False,
                reason="missing_validation_report",
                details={"baselineId": baseline.baseline_id},
            )

        if not report.is_publish_eligible:
            return BaselineEligibilityView(
                eligible=False,
                reason="validation_not_eligible",
                details={
                    "baselineId": baseline.baseline_id,
                    "validationStatus": report.status.value,
                },
            )

        return BaselineEligibilityView(
            eligible=True,
            reason="eligible",
            details={
                "baselineId": baseline.baseline_id,
                "validationStatus": report.status.value,
            },
        )


class BaselineSelectionService:
    def __init__(
        self,
        baselines: BaselineRepository,
        validation_eligibility: BaselineValidationEligibilityService,
    ) -> None:
        self._baselines = baselines
        self._validation_eligibility = validation_eligibility

    def select_for_publish(
        self,
        *,
        source: DataSource,
        target,
        profile,
    ) -> SanitizedBaseline:
        candidates = self._baselines.list_active_for_system(source.system_id)
        compatible = [
            baseline
            for baseline in candidates
            if baseline.is_compatible_with(
                source=source,
                target=target,
                profile=profile,
            )
        ]
        if not compatible:
            raise DomainError(
                "No compatible active sanitized baseline is available for the selected"
                " system, profile, and target environment."
            )

        compatible.sort(key=lambda baseline: baseline.refreshed_at, reverse=True)
        for baseline in compatible:
            try:
                report = self._validation_eligibility.require_publish_eligible(baseline)
                return baseline, report
            except DomainError:
                continue

        raise DomainError(
            "No compatible sufficiently validated sanitized baseline is available for the"
            " selected system, profile, and target environment."
        )


class PublishSourceResolutionService:
    def __init__(self, baseline_selection: BaselineSelectionService) -> None:
        self._baseline_selection = baseline_selection

    def resolve_for_publish(
        self,
        *,
        source: DataSource,
        target,
        profile,
    ) -> tuple[SanitizedBaseline | None, ValidationReport | None]:
        if not profile.uses_sanitized_baseline:
            return None, None
        return self._baseline_selection.select_for_publish(
            source=source,
            target=target,
            profile=profile,
        )


class BaselineQueryService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        baselines: BaselineRepository,
        validations: ValidationLookupService,
        validation_summary: PublishValidationSummaryService,
        eligibility: BaselineEligibilityExplanationService,
    ) -> None:
        self._systems = systems
        self._baselines = baselines
        self._validations = validations
        self._validation_summary = validation_summary
        self._eligibility = eligibility

    def list_baselines(
        self,
        *,
        system_id: str | None = None,
        target_environment_type: str | None = None,
        dataset_profile_id: str | None = None,
    ) -> BaselineListingView:
        filters = {
            key: value
            for key, value in {
                "systemId": system_id,
                "targetEnvironmentType": target_environment_type,
                "datasetProfileId": dataset_profile_id,
            }.items()
            if value is not None
        }

        if system_id is None:
            baselines = []
            for system in self._systems.list_active():
                baselines.extend(self._baselines.list_active_for_system(system.system_id))
        else:
            baselines = list(self._baselines.list_active_for_system(system_id))

        if target_environment_type is not None:
            baselines = [
                baseline
                for baseline in baselines
                if baseline.target_environment_type.value == target_environment_type
            ]
        if dataset_profile_id is not None:
            baselines = [
                baseline
                for baseline in baselines
                if baseline.dataset_profile_id == dataset_profile_id
            ]

        baselines.sort(key=lambda baseline: baseline.refreshed_at, reverse=True)
        items = [self._to_list_item(baseline) for baseline in baselines]
        return BaselineListingView(filters=filters, items=items)

    def get_baseline(self, baseline_id: str) -> BaselineDetailView:
        baseline = self._baselines.get_by_id(baseline_id)
        if baseline is None:
            raise DomainError(f"Unknown sanitized baseline: {baseline_id}")
        report = self._validations.get_latest_for_baseline(baseline.baseline_id)
        return BaselineDetailView.from_baseline(
            baseline,
            publish_eligible=(False if report is None else report.is_publish_eligible),
            eligibility=self._eligibility.explain(baseline, report),
            validation_summary=self._validation_summary.summarize_baseline(report),
        )

    def _to_list_item(self, baseline: SanitizedBaseline) -> BaselineListItemView:
        report = self._validations.get_latest_for_baseline(baseline.baseline_id)
        return BaselineListItemView(
            baseline_id=baseline.baseline_id,
            system_id=baseline.system_id,
            system_name=baseline.system_name,
            source_id=baseline.source_id,
            dataset_profile_id=baseline.dataset_profile_id,
            target_environment_type=baseline.target_environment_type.value,
            engine_type=baseline.engine_type.value,
            version=baseline.version,
            status=baseline.status.value,
            refreshed_at=baseline.refreshed_at,
            publish_eligible=(False if report is None else report.is_publish_eligible),
            eligibility=self._eligibility.explain(baseline, report),
            validation_summary=self._validation_summary.summarize_baseline(report),
        )


class PolicyCoverageQueryService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        coverage: PolicyCoverageEvaluationService,
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._coverage = coverage

    def get_policy_coverage(self, system_id: str) -> PolicyCoverageReportView:
        resolve_active_system(self._systems, system_id)
        source = resolve_active_source_for_system(
            self._systems,
            self._data_sources,
            system_id,
        )
        report = self._coverage.evaluate_for_source(source)
        return PolicyCoverageReportView.from_report(report)


class BaselineRefreshRequestService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        data_sources: DataSourceRepository,
        dataset_profiles: DatasetProfileRepository,
        refresh_jobs: BaselineRefreshJobRepository,
        refresh_queue: BaselineRefreshQueuePort,
        audits: AuditEventRepository,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._systems = systems
        self._data_sources = data_sources
        self._dataset_profiles = dataset_profiles
        self._refresh_jobs = refresh_jobs
        self._refresh_queue = refresh_queue
        self._audits = audits
        self._clock = clock
        self._ids = ids

    def create_job(self, command: CreateBaselineRefreshJobCommand) -> BaselineRefreshJobView:
        system = resolve_active_system(self._systems, command.system_id)
        source = resolve_active_source_for_system(
            self._systems,
            self._data_sources,
            command.system_id,
        )
        profile = self._require_active_profile(command.dataset_profile_id)
        try:
            target_environment_type = EnvironmentType(command.target_environment_type)
        except ValueError as exc:
            raise DomainError(
                f"Unsupported target environment type: {command.target_environment_type}"
            ) from exc

        if profile.system_id != system.system_id:
            raise DomainError("Dataset profile does not belong to the selected system.")
        if profile.target_environment_type != target_environment_type:
            raise DomainError(
                "Dataset profile is not approved for the selected target environment."
            )

        now = self._clock.now()
        job = BaselineRefreshJob.create(
            job_id=self._ids.new_id("baseline-refresh"),
            system_id=system.system_id,
            dataset_profile_id=profile.profile_id,
            target_environment_type=target_environment_type,
            requested_by=command.requested_by,
            trigger_type=command.trigger_type,
            refresh_schedule_id=command.refresh_schedule_id,
            created_at=now,
        )
        self._refresh_jobs.add(job)
        self._refresh_queue.enqueue(job.job_id)
        self._audits.add(
            AuditEvent(
                event_id=self._ids.new_id("audit"),
                event_type="baseline_refresh_requested",
                actor=command.requested_by,
                subject_type="baseline_refresh_job",
                subject_id=job.job_id,
                details={
                    "systemId": system.system_id,
                    "sourceId": source.source_id,
                    "datasetProfileId": profile.profile_id,
                    "targetEnvironmentType": target_environment_type.value,
                },
                created_at=now,
            )
        )
        return BaselineRefreshJobView.from_job(job)

    def _require_active_profile(self, profile_id: str):
        profile = self._dataset_profiles.get_by_id(profile_id)
        if profile is None or not profile.active:
            raise DomainError(f"Unknown or inactive dataset profile: {profile_id}")
        return profile


class BaselineRefreshMonitoringService:
    def __init__(self, refresh_jobs: BaselineRefreshJobRepository) -> None:
        self._refresh_jobs = refresh_jobs

    def list_jobs(self) -> list[BaselineRefreshJobView]:
        jobs = sorted(
            self._refresh_jobs.list_all(),
            key=lambda job: job.created_at,
            reverse=True,
        )
        return [BaselineRefreshJobView.from_job(job) for job in jobs]

    def get_job(self, job_id: str) -> BaselineRefreshJobView:
        job = self._refresh_jobs.get_by_id(job_id)
        if job is None:
            raise DomainError(f"Unknown baseline refresh job: {job_id}")
        return BaselineRefreshJobView.from_job(job)


class RefreshScheduleService:
    def __init__(
        self,
        *,
        systems: SystemRepository,
        dataset_profiles: DatasetProfileRepository,
        schedules: BaselineRefreshScheduleRepository,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._systems = systems
        self._dataset_profiles = dataset_profiles
        self._schedules = schedules
        self._clock = clock
        self._ids = ids

    def create_schedule(self, command: CreateRefreshScheduleCommand) -> RefreshScheduleView:
        if command.interval_minutes <= 0:
            raise DomainError("Refresh schedule interval_minutes must be greater than zero.")

        system = resolve_active_system(self._systems, command.system_id)
        profile = self._require_active_profile(command.dataset_profile_id)
        try:
            target_environment_type = EnvironmentType(command.target_environment_type)
        except ValueError as exc:
            raise DomainError(
                f"Unsupported target environment type: {command.target_environment_type}"
            ) from exc

        if profile.system_id != system.system_id:
            raise DomainError("Dataset profile does not belong to the selected system.")
        if profile.target_environment_type != target_environment_type:
            raise DomainError(
                "Dataset profile is not approved for the selected target environment."
            )

        now = self._clock.now()
        schedule = BaselineRefreshSchedule(
            schedule_id=self._ids.new_id("refresh-schedule"),
            system_id=system.system_id,
            dataset_profile_id=profile.profile_id,
            target_environment_type=target_environment_type,
            interval_minutes=command.interval_minutes,
            status=RefreshScheduleStatus.ENABLED,
            created_by=command.created_by,
            created_at=now,
            updated_at=now,
            next_run_at=now,
        )
        self._schedules.add(schedule)
        return RefreshScheduleView.from_schedule(schedule)

    def list_schedules(self) -> list[RefreshScheduleView]:
        schedules = sorted(
            self._schedules.list_all(),
            key=lambda schedule: schedule.created_at,
            reverse=True,
        )
        return [RefreshScheduleView.from_schedule(schedule) for schedule in schedules]

    def _require_active_profile(self, profile_id: str):
        profile = self._dataset_profiles.get_by_id(profile_id)
        if profile is None or not profile.active:
            raise DomainError(f"Unknown or inactive dataset profile: {profile_id}")
        return profile


class RefreshScheduleDispatchService:
    def __init__(
        self,
        *,
        schedules: BaselineRefreshScheduleRepository,
        refresh_jobs: BaselineRefreshJobRepository,
        refresh_requests: BaselineRefreshRequestService,
        clock: ClockPort,
    ) -> None:
        self._schedules = schedules
        self._refresh_jobs = refresh_jobs
        self._refresh_requests = refresh_requests
        self._clock = clock

    def dispatch_due_schedules(self) -> list[BaselineRefreshJobView]:
        now = self._clock.now()
        dispatched: list[BaselineRefreshJobView] = []

        for schedule in self._schedules.list_enabled():
            if not schedule.is_due(now):
                continue
            if self._has_pending_job(schedule.schedule_id):
                continue

            job = self._refresh_requests.create_job(
                CreateBaselineRefreshJobCommand(
                    system_id=schedule.system_id,
                    dataset_profile_id=schedule.dataset_profile_id,
                    target_environment_type=schedule.target_environment_type.value,
                    requested_by="scheduler",
                    trigger_type="scheduled",
                    refresh_schedule_id=schedule.schedule_id,
                )
            )
            self._schedules.save(schedule.mark_dispatched(dispatched_at=now))
            dispatched.append(job)

        return dispatched

    def _has_pending_job(self, schedule_id: str) -> bool:
        for job in self._refresh_jobs.list_all():
            if job.refresh_schedule_id != schedule_id:
                continue
            if job.status in {
                BaselineRefreshStatus.REQUESTED,
                BaselineRefreshStatus.RUNNING,
            }:
                return True
        return False


class LineageRecordingService:
    def __init__(
        self,
        *,
        lineage: LineageRepository,
        validations: ValidationLookupService,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._lineage = lineage
        self._validations = validations
        self._clock = clock
        self._ids = ids

    def record_refresh_completion(
        self,
        *,
        job: BaselineRefreshJob,
        baseline: SanitizedBaseline,
    ) -> None:
        created_at = self._clock.now()
        self._lineage.add(
            LineageRecord(
                record_id=self._ids.new_id("lineage"),
                source_type="baseline_refresh_job",
                source_id=job.job_id,
                target_type="sanitized_baseline",
                target_id=baseline.baseline_id,
                event_type="baseline_materialized",
                created_at=created_at,
                details={
                    "systemId": job.system_id,
                    "datasetProfileId": job.dataset_profile_id,
                    "baselineVersion": baseline.version,
                },
            )
        )
        report = self._validations.get_latest_for_baseline(baseline.baseline_id)
        if report is not None:
            self._lineage.add(
                LineageRecord(
                    record_id=self._ids.new_id("lineage"),
                    source_type="validation_report",
                    source_id=report.report_id,
                    target_type="sanitized_baseline",
                    target_id=baseline.baseline_id,
                    event_type="baseline_validated",
                    created_at=created_at,
                    details={
                        "validationStatus": report.status.value,
                        "warningCount": report.warning_count,
                        "errorCount": report.error_count,
                    },
                )
            )

    def record_publish_completion(
        self,
        *,
        job: PublishJob,
        baseline: SanitizedBaseline | None,
    ) -> None:
        if baseline is None:
            return
        created_at = self._clock.now()
        self._lineage.add(
            LineageRecord(
                record_id=self._ids.new_id("lineage"),
                source_type="sanitized_baseline",
                source_id=baseline.baseline_id,
                target_type="publish_job",
                target_id=job.job_id,
                event_type="baseline_published",
                created_at=created_at,
                details={
                    "baselineVersion": baseline.version,
                    "datasetProfileId": job.dataset_profile_id,
                },
            )
        )
        report = self._validations.get_latest_for_baseline(baseline.baseline_id)
        if report is not None:
            self._lineage.add(
                LineageRecord(
                    record_id=self._ids.new_id("lineage"),
                    source_type="validation_report",
                    source_id=report.report_id,
                    target_type="publish_job",
                    target_id=job.job_id,
                    event_type="publish_used_validated_baseline",
                    created_at=created_at,
                    details={
                        "validationStatus": report.status.value,
                        "warningCount": report.warning_count,
                        "errorCount": report.error_count,
                    },
                )
            )

    def record_extraction_completion(
        self,
        *,
        job: ExtractionJob,
        plan: ExtractionPlan,
        plan_snapshot: ExtractionPlanSnapshot | None = None,
    ) -> None:
        created_at = self._clock.now()
        self._lineage.add(
            LineageRecord(
                record_id=self._ids.new_id("lineage"),
                source_type="data_source",
                source_id=job.source_id,
                target_type="extraction_job",
                target_id=job.job_id,
                event_type="extraction_from_source",
                created_at=created_at,
                details={
                    "systemId": job.system_id,
                    "selectedObjectCount": len(plan.selected_object_ids),
                    "selectedRelationshipCount": len(plan.selected_relationship_ids),
                },
            )
        )
        self._lineage.add(
            LineageRecord(
                record_id=self._ids.new_id("lineage"),
                source_type="metadata_object",
                source_id=job.root_object_id,
                target_type="extraction_job",
                target_id=job.job_id,
                event_type="extraction_root_selected",
                created_at=created_at,
                details={
                    "includeRelated": job.include_related,
                    "maxDepth": job.max_depth,
                },
            )
        )
        for object_id in plan.selected_object_ids:
            self._lineage.add(
                LineageRecord(
                    record_id=self._ids.new_id("lineage"),
                    source_type="extraction_job",
                    source_id=job.job_id,
                    target_type="metadata_object",
                    target_id=object_id,
                    event_type="extraction_plan_includes_object",
                    created_at=created_at,
                    details={
                        "isRootObject": object_id == job.root_object_id,
                    },
                )
            )
        if plan_snapshot is not None:
            self._lineage.add(
                LineageRecord(
                    record_id=self._ids.new_id("lineage"),
                    source_type="extraction_plan_snapshot",
                    source_id=plan_snapshot.snapshot_id,
                    target_type="extraction_job",
                    target_id=job.job_id,
                    event_type="extraction_executed_from_plan_snapshot",
                    created_at=created_at,
                    details={
                        "selectedObjectCount": len(plan_snapshot.selected_object_ids),
                        "selectedRelationshipCount": len(plan_snapshot.selected_relationship_ids),
                    },
                )
            )


class LineageQueryService:
    def __init__(self, lineage: LineageRepository) -> None:
        self._lineage = lineage

    def get_baseline_lineage(self, baseline_id: str) -> LineageView:
        records = self._list_related("sanitized_baseline", baseline_id)
        return LineageView(
            subject_type="sanitized_baseline",
            subject_id=baseline_id,
            items=[LineageRecordView.from_record(record) for record in records],
        )

    def get_publish_job_lineage(self, job_id: str) -> LineageView:
        records = self._list_related("publish_job", job_id)
        return LineageView(
            subject_type="publish_job",
            subject_id=job_id,
            items=[LineageRecordView.from_record(record) for record in records],
        )

    def get_extraction_job_lineage(self, job_id: str) -> LineageView:
        records = self._list_related("extraction_job", job_id)
        return LineageView(
            subject_type="extraction_job",
            subject_id=job_id,
            items=[LineageRecordView.from_record(record) for record in records],
        )

    def _list_related(self, reference_type: str, reference_id: str) -> list[LineageRecord]:
        records = self._lineage.list_related(
            reference_type=reference_type,
            reference_id=reference_id,
        )
        return sorted(records, key=lambda record: record.created_at)


class PublishRequestService:
    def __init__(
        self,
        *,
        data_sources: DataSourceRepository,
        environments: TargetEnvironmentRepository,
        dataset_profiles: DatasetProfileRepository,
        jobs: PublishJobRepository,
        audits: AuditEventRepository,
        queue: JobQueuePort,
        policy: PolicyPort,
        readiness: PublishReadinessValidationService,
        publish_source_resolution: PublishSourceResolutionService,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._data_sources = data_sources
        self._environments = environments
        self._dataset_profiles = dataset_profiles
        self._jobs = jobs
        self._audits = audits
        self._queue = queue
        self._policy = policy
        self._readiness = readiness
        self._publish_source_resolution = publish_source_resolution
        self._clock = clock
        self._ids = ids

    def create_job(self, command: CreatePublishJobCommand) -> JobView:
        source = self._require_active_source(command.source_id)
        target = self._require_active_target(command.target_environment_id)
        profile = self._require_active_profile(command.dataset_profile_id)

        if profile.system_id != source.system_id:
            raise DomainError("Dataset profile does not belong to the selected system.")
        if profile.target_environment_type != target.environment_type:
            raise DomainError(
                "Dataset profile is not approved for the selected target environment."
            )
        if source.engine_type != target.engine_type:
            raise DomainError(
                "Source and target database engines must match in the first implementation."
            )

        self._policy.assert_publish_allowed(
            source=source,
            target=target,
            profile=profile,
            requested_by=command.requested_by,
        )
        self._readiness.assert_publish_ready(source)
        selected_baseline, validation_report = self._publish_source_resolution.resolve_for_publish(
            source=source,
            target=target,
            profile=profile,
        )

        now = self._clock.now()
        job = PublishJob.create(
            job_id=self._ids.new_id("job"),
            source_id=source.source_id,
            sanitized_baseline_id=(
                None if selected_baseline is None else selected_baseline.baseline_id
            ),
            baseline_validation_status=(
                None if validation_report is None else validation_report.status
            ),
            baseline_validation_warning_count=(
                0 if validation_report is None else validation_report.warning_count
            ),
            baseline_validation_error_count=(
                0 if validation_report is None else validation_report.error_count
            ),
            baseline_validated_at=(
                None if validation_report is None else validation_report.created_at
            ),
            target_environment_id=target.environment_id,
            dataset_profile_id=profile.profile_id,
            requested_by=command.requested_by,
            created_at=now,
        )
        self._jobs.add(job)
        self._queue.enqueue(job.job_id)

        self._audits.add(
            AuditEvent(
                event_id=self._ids.new_id("audit"),
                event_type="publish_job_requested",
                actor=command.requested_by,
                subject_type="publish_job",
                subject_id=job.job_id,
                details={
                    "sourceId": source.source_id,
                    "sanitizedBaselineId": job.sanitized_baseline_id,
                    "baselineValidationStatus": (
                        None
                        if job.baseline_validation_status is None
                        else job.baseline_validation_status.value
                    ),
                    "targetEnvironmentId": target.environment_id,
                    "datasetProfileId": profile.profile_id,
                },
                created_at=now,
            )
        )
        return JobView.from_job(job)

    def get_job(self, job_id: str) -> JobView:
        job = self._jobs.get_by_id(job_id)
        if job is None:
            raise DomainError(f"Unknown publish job: {job_id}")
        return JobView.from_job(job)

    def _require_active_source(self, source_id: str):
        source = self._data_sources.get_by_id(source_id)
        if source is None or not source.active:
            raise DomainError(f"Unknown or inactive source: {source_id}")
        return source

    def _require_active_target(self, environment_id: str):
        target = self._environments.get_by_id(environment_id)
        if target is None or not target.active:
            raise DomainError(f"Unknown or inactive target environment: {environment_id}")
        return target

    def _require_active_profile(self, profile_id: str):
        profile = self._dataset_profiles.get_by_id(profile_id)
        if profile is None or not profile.active:
            raise DomainError(f"Unknown or inactive dataset profile: {profile_id}")
        return profile


class JobMonitoringService:
    def __init__(
        self,
        jobs: PublishJobRepository,
        audits: AuditEventRepository,
    ) -> None:
        self._jobs = jobs
        self._audits = audits

    def get_job(self, job_id: str) -> JobView:
        job = self._jobs.get_by_id(job_id)
        if job is None:
            raise DomainError(f"Unknown publish job: {job_id}")
        return JobView.from_job(job)

    def list_audit_events(self, subject_id: str):
        return self._audits.list_for_subject(subject_id)
