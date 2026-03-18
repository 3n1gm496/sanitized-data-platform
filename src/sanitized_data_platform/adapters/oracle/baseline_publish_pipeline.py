from __future__ import annotations

import hashlib
import json

from sanitized_data_platform.adapters.oracle.artifact_publish_pipeline import (
    OracleArtifactPublishPipelineAdapter,
)
from sanitized_data_platform.application.ports import BaselineAssetRepository
from sanitized_data_platform.domain.entities import PublishJob, SanitizedBaseline
from sanitized_data_platform.domain.enums import DatabaseEngine, ExtractionArtifactFormat
from sanitized_data_platform.domain.errors import DomainError


class OracleBaselinePublishPipelineAdapter(OracleArtifactPublishPipelineAdapter):
    def __init__(self, *, baseline_assets: BaselineAssetRepository, connect) -> None:
        super().__init__(connect=connect)
        self._baseline_assets = baseline_assets

    def execute(
        self,
        *,
        job: PublishJob,
        source,
        baseline: SanitizedBaseline | None,
        target,
        profile,
    ) -> dict[str, object]:
        if baseline is None:
            raise DomainError("Oracle baseline publish requires a selected sanitized baseline.")
        if target.engine_type != DatabaseEngine.ORACLE:
            raise DomainError(
                "Oracle baseline publish pipeline adapter can only execute oracle targets."
            )
        assets = sorted(
            self._baseline_assets.list_for_baseline(baseline.baseline_id),
            key=lambda asset: (asset.import_order, asset.root_object_id),
        )
        if not assets:
            raise DomainError(
                f"No materialized baseline assets are available for baseline: {baseline.baseline_id}"
            )
        connection = self._connect(target.target_endpoint)
        cursor = connection.cursor()
        imported_tables: list[str] = []
        imported_rows = 0
        try:
            for asset in assets:
                if asset.artifact_format != ExtractionArtifactFormat.JSONL:
                    raise DomainError(
                        "Oracle baseline publish currently supports only JSONL baseline assets."
                    )
                if not asset.root_object_id.startswith("table:"):
                    raise DomainError(
                        "Oracle baseline publish currently supports only root-table baseline assets."
                    )
                owner, table_name = self._parse_root_table(asset.root_object_id)
                checksum = hashlib.sha256()
                inserted_row_count = 0
                with open(asset.artifact_path, encoding="utf-8") as artifact_file:
                    column_names = None
                    column_specs = None
                    insert_sql = None
                    for raw_line in artifact_file:
                        checksum.update(raw_line.encode("utf-8"))
                        line = raw_line.strip()
                        if not line:
                            continue
                        row = json.loads(line)
                        if not isinstance(row, dict):
                            raise DomainError(
                                "Baseline publish expects JSONL rows as JSON objects."
                            )
                        if column_names is None:
                            column_names = [str(name) for name in row.keys()]
                            self._validate_columns(column_names)
                            column_specs = self._load_target_table_projection(
                                cursor=cursor,
                                owner=owner,
                                table_name=table_name,
                                column_names=column_names,
                            )
                            insert_sql = self._build_insert_sql(
                                owner=owner,
                                table_name=table_name,
                                column_names=column_names,
                            )
                        elif [str(name) for name in row.keys()] != column_names:
                            raise DomainError(
                                "Baseline publish requires a consistent JSONL column projection."
                            )
                        assert column_specs is not None
                        self._validate_row_values(row=row, column_specs=column_specs)
                        assert insert_sql is not None
                        values = tuple(row[column_name] for column_name in column_names)
                        cursor.execute(insert_sql, values)
                        inserted_row_count += 1
                actual_checksum = checksum.hexdigest()
                if asset.checksum is not None and actual_checksum != asset.checksum:
                    raise DomainError(
                        f"Baseline asset checksum verification failed before commit: {asset.asset_id}"
                    )
                if asset.row_count != inserted_row_count:
                    raise DomainError(
                        f"Baseline asset row count verification failed before commit: {asset.asset_id}"
                    )
                imported_tables.append(f"{owner}.{table_name}")
                imported_rows += inserted_row_count
            connection.commit()
        except Exception:
            if hasattr(connection, "rollback"):
                connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

        return {
            "baselineStrategy": "oracle-materialized-baseline",
            "baselineId": baseline.baseline_id,
            "baselineVersion": baseline.version,
            "targetEnvironmentId": target.environment_id,
            "importedTableCount": len(imported_tables),
            "importedTables": imported_tables,
            "rowsPublished": imported_rows,
            "validationStatus": (
                None
                if job.baseline_validation_status is None
                else job.baseline_validation_status.value
            ),
        }
