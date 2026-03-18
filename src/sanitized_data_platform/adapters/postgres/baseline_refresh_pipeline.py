from __future__ import annotations

from collections import defaultdict

from sanitized_data_platform.adapters.postgres.extraction_pipeline import (
    PostgreSQLExtractionPipelineAdapter,
)
from sanitized_data_platform.application.ports import (
    ClockPort,
    DataSourceRepository,
    MetadataCatalogRepository,
    TokenVaultPort,
    TransformationPolicyRepository,
)
from sanitized_data_platform.domain.entities import (
    BaselineRefreshJob,
    DataSource,
    DatasetProfile,
    ExtractionJob,
    ExtractionPlan,
    ExtractionRoot,
    MetadataObject,
    Relationship,
    SanitizedBaseline,
    TraversalRule,
    utc_now,
)
from sanitized_data_platform.domain.enums import (
    DatabaseEngine,
    DatasetMode,
    ExtractionArtifactKind,
    MetadataObjectType,
)
from sanitized_data_platform.domain.errors import DomainError


class PostgreSQLBaselineRefreshPipelineAdapter:
    def __init__(
        self,
        *,
        metadata_catalog: MetadataCatalogRepository,
        data_sources: DataSourceRepository,
        connect,
        policies: TransformationPolicyRepository | None = None,
        token_vault: TokenVaultPort | None = None,
        artifact_dir: str | None = None,
        clock: ClockPort | None = None,
    ) -> None:
        self._metadata_catalog = metadata_catalog
        self._clock = clock
        self._extraction = PostgreSQLExtractionPipelineAdapter(
            data_sources=data_sources,
            connect=connect,
            policies=policies,
            token_vault=token_vault,
            artifact_dir=artifact_dir,
        )

    def execute(
        self,
        *,
        job: BaselineRefreshJob,
        source: DataSource,
        profile: DatasetProfile,
        existing_baseline: SanitizedBaseline | None,
    ) -> dict[str, object]:
        if source.engine_type != DatabaseEngine.POSTGRES:
            raise DomainError(
                "PostgreSQL baseline refresh pipeline adapter can only execute postgres data sources."
            )
        if profile.dataset_mode != DatasetMode.FULL_CLONE:
            raise DomainError(
                "PostgreSQL baseline refresh currently supports only full-clone dataset profiles."
            )

        tables = self._list_materializable_tables(source.source_id)
        if not tables:
            raise DomainError(
                f"No materializable catalog tables are available for baseline refresh: {source.source_id}"
            )

        relationships = self._metadata_catalog.list_relationships(source.source_id)
        ordered_tables = self._order_tables(
            source_id=source.source_id,
            tables=tables,
            relationships=relationships,
        )

        created_at = self._now()
        baseline_assets: list[dict[str, object]] = []
        rows_materialized = 0
        notes: list[str] = []
        for import_order, table in enumerate(ordered_tables):
            plan = ExtractionPlan(
                source_id=source.source_id,
                root=ExtractionRoot(
                    object_id=table.object_id,
                    artifact_kind=ExtractionArtifactKind.FULL,
                ),
                traversal_rule=TraversalRule(include_related=False, max_depth=0),
                selected_object_ids=(table.object_id,),
                selected_relationship_ids=(),
            )
            extraction_job = ExtractionJob.create(
                job_id=f"{job.job_id}:{table.object_id}",
                source_id=source.source_id,
                system_id=job.system_id,
                plan_snapshot_id=f"{job.job_id}:{table.object_id}:snapshot",
                root_object_id=table.object_id,
                criteria=(),
                include_related=False,
                max_depth=0,
                requested_by=job.requested_by,
                created_at=created_at,
            )
            summary = self._extraction.execute(job=extraction_job, plan=plan)
            baseline_assets.append(
                {
                    "artifactPath": summary["artifactPath"],
                    "rootObjectId": table.object_id,
                    "rowCount": int(summary["materializedRowCount"]),
                    "checksum": summary["artifactChecksum"],
                    "columnCount": summary["artifactColumnCount"],
                    "importOrder": import_order,
                }
            )
            rows_materialized += int(summary["materializedRowCount"])
            for note in summary.get("notes", []):
                if isinstance(note, str):
                    notes.append(note)

        result: dict[str, object] = {
            "refreshStrategy": "postgres-materialized-baseline",
            "version": created_at.strftime("%Y.%m.%d.%H%M"),
            "reusedBaseline": existing_baseline is not None,
            "materializedTableCount": len(baseline_assets),
            "rowsMaterialized": rows_materialized,
            "baselineAssets": baseline_assets,
        }
        if notes:
            result["notes"] = notes
        return result

    def _list_materializable_tables(self, source_id: str) -> list[MetadataObject]:
        tables = [
            item
            for item in self._metadata_catalog.list_objects(
                source_id,
                object_type=MetadataObjectType.TABLE,
            )
            if item.active
        ]
        return sorted(tables, key=lambda item: item.qualified_name)

    def _order_tables(
        self,
        *,
        source_id: str,
        tables: list[MetadataObject],
        relationships: list[Relationship],
    ) -> list[MetadataObject]:
        table_by_id = {table.object_id: table for table in tables}
        table_ids = set(table_by_id)
        parent_table_by_column: dict[str, str] = {}
        for item in self._metadata_catalog.list_objects(source_id):
            if (
                item.active
                and item.object_type == MetadataObjectType.COLUMN
                and item.parent_object_id in table_ids
            ):
                parent_table_by_column[item.object_id] = str(item.parent_object_id)

        outgoing: dict[str, set[str]] = defaultdict(set)
        inbound_count = {table_id: 0 for table_id in table_ids}
        for relationship in relationships:
            if not relationship.active or relationship.relationship_type != "foreign_key":
                continue
            source_table_id = parent_table_by_column.get(relationship.source_object_id)
            target_table_id = parent_table_by_column.get(relationship.target_object_id)
            if source_table_id is None or target_table_id is None:
                continue
            if source_table_id == target_table_id:
                continue
            if source_table_id not in table_ids or target_table_id not in table_ids:
                continue
            if source_table_id in outgoing[target_table_id]:
                continue
            outgoing[target_table_id].add(source_table_id)
            inbound_count[source_table_id] += 1

        ready = sorted(
            [table_by_id[table_id] for table_id, count in inbound_count.items() if count == 0],
            key=lambda item: item.qualified_name,
        )
        ordered: list[MetadataObject] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for dependent_id in sorted(
                outgoing.get(current.object_id, set()),
                key=lambda table_id: table_by_id[table_id].qualified_name,
            ):
                inbound_count[dependent_id] -= 1
                if inbound_count[dependent_id] == 0:
                    ready.append(table_by_id[dependent_id])
                    ready.sort(key=lambda item: item.qualified_name)

        if len(ordered) == len(tables):
            return ordered

        remaining = [
            table_by_id[table_id]
            for table_id in table_ids
            if table_id not in {item.object_id for item in ordered}
        ]
        remaining.sort(key=lambda item: item.qualified_name)
        return [*ordered, *remaining]

    def _now(self):
        if self._clock is None:
            return utc_now()
        return self._clock.now()
