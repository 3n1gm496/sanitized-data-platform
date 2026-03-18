from datetime import datetime, timezone
import os
import tempfile

import pytest

from sanitized_data_platform.adapters.oracle.baseline_refresh_pipeline import (
    OracleBaselineRefreshPipelineAdapter,
)
from sanitized_data_platform.domain.entities import BaselineRefreshJob
from sanitized_data_platform.domain.enums import BaselineRefreshStatus, DatabaseEngine
from sanitized_data_platform.domain.errors import DomainError

from tests.fakes import (
    FakeClock,
    InMemoryDataSourceRepository,
    InMemoryMetadataCatalogRepository,
    sample_profile,
)
from tests.oracle_helpers import (
    OracleExtractionConnection,
    oracle_metadata_objects,
    oracle_relationships,
    sample_oracle_source,
)


def refresh_job() -> BaselineRefreshJob:
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return BaselineRefreshJob(
        job_id="baseline-refresh-1",
        system_id="crm",
        dataset_profile_id="profile-full-sanitized",
        target_environment_type=sample_profile().target_environment_type,
        requested_by="steward@example.internal",
        trigger_type="manual",
        refresh_schedule_id=None,
        status=BaselineRefreshStatus.RUNNING,
        baseline_id=None,
        created_at=created_at,
        updated_at=created_at,
        result_summary={},
    )


def test_oracle_baseline_refresh_pipeline_materializes_catalog_tables_in_fk_order():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = OracleBaselineRefreshPipelineAdapter(
            metadata_catalog=InMemoryMetadataCatalogRepository(
                oracle_metadata_objects(),
                oracle_relationships(),
            ),
            data_sources=InMemoryDataSourceRepository([sample_oracle_source()]),
            connect=lambda _endpoint: OracleExtractionConnection(
                row_count=2,
                sample_rows=[(1, "a@example.internal"), (2, "b@example.internal")],
                sample_columns=("CUSTOMER_ID", "EMAIL"),
                table_columns=("CUSTOMER_ID", "EMAIL"),
                pk_columns=("CUSTOMER_ID",),
                executed=executed,
            ),
            artifact_dir=artifact_dir,
            clock=FakeClock(),
        )

        summary = adapter.execute(
            job=refresh_job(),
            source=sample_oracle_source(),
            profile=sample_profile(),
            existing_baseline=None,
        )

        assert summary["refreshStrategy"] == "oracle-materialized-baseline"
        assert summary["version"] == "2026.01.01.0000"
        assert summary["reusedBaseline"] is False
        assert summary["materializedTableCount"] == 2
        assert summary["rowsMaterialized"] == 4
        assert [item["rootObjectId"] for item in summary["baselineAssets"]] == [
            "table:source-crm-oracle:CRM.CUSTOMERS",
            "table:source-crm-oracle:CRM.ORDERS",
        ]
        assert [item["importOrder"] for item in summary["baselineAssets"]] == [0, 1]
        for asset in summary["baselineAssets"]:
            assert os.path.exists(asset["artifactPath"])


def test_oracle_baseline_refresh_pipeline_rejects_missing_catalog_tables():
    adapter = OracleBaselineRefreshPipelineAdapter(
        metadata_catalog=InMemoryMetadataCatalogRepository(objects=[], relationships=[]),
        data_sources=InMemoryDataSourceRepository([sample_oracle_source()]),
        connect=lambda _endpoint: OracleExtractionConnection(
            row_count=0,
            sample_rows=[],
            sample_columns=(),
            table_columns=(),
            pk_columns=(),
            executed=[],
        ),
        clock=FakeClock(),
    )

    with pytest.raises(DomainError, match="No materializable catalog tables are available"):
        adapter.execute(
            job=refresh_job(),
            source=sample_oracle_source(),
            profile=sample_profile(),
            existing_baseline=None,
        )


def test_oracle_baseline_refresh_pipeline_rejects_non_oracle_sources():
    adapter = OracleBaselineRefreshPipelineAdapter(
        metadata_catalog=InMemoryMetadataCatalogRepository(
            oracle_metadata_objects(),
            oracle_relationships(),
        ),
        data_sources=InMemoryDataSourceRepository([sample_oracle_source()]),
        connect=lambda _endpoint: OracleExtractionConnection(
            row_count=0,
            sample_rows=[],
            sample_columns=(),
            table_columns=(),
            pk_columns=(),
            executed=[],
        ),
        clock=FakeClock(),
    )
    source = sample_oracle_source()
    non_oracle_source = type(source)(
        source_id=source.source_id,
        system_id=source.system_id,
        system_name=source.system_name,
        engine_type=DatabaseEngine.POSTGRES,
        endpoint=source.endpoint,
        database_name=source.database_name,
        access_mode=source.access_mode,
        replica_preferred=source.replica_preferred,
        active=source.active,
    )

    with pytest.raises(DomainError, match="can only execute oracle data sources"):
        adapter.execute(
            job=refresh_job(),
            source=non_oracle_source,
            profile=sample_profile(),
            existing_baseline=None,
        )


def test_oracle_baseline_refresh_pipeline_cleans_up_created_artifacts_on_failure():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = OracleBaselineRefreshPipelineAdapter(
            metadata_catalog=InMemoryMetadataCatalogRepository(
                oracle_metadata_objects(),
                oracle_relationships(),
            ),
            data_sources=InMemoryDataSourceRepository([sample_oracle_source()]),
            connect=lambda _endpoint: OracleExtractionConnection(
                row_count=2,
                sample_rows=[(1, "a@example.internal"), (2, "b@example.internal")],
                sample_columns=("CUSTOMER_ID", "EMAIL"),
                table_columns=("CUSTOMER_ID", "EMAIL"),
                pk_columns=("CUSTOMER_ID",),
                executed=executed,
            ),
            artifact_dir=artifact_dir,
            clock=FakeClock(),
        )

        original = adapter._list_materializable_tables
        def broken_list(source_id: str):
            return original(source_id)[:1] + original(source_id)[1:]
        # force failure on second execution by monkey patching connection data shape
        adapter._list_materializable_tables = broken_list  # type: ignore[method-assign]
        adapter._extraction = type(adapter._extraction)(
            data_sources=InMemoryDataSourceRepository([sample_oracle_source()]),
            connect=lambda _endpoint: OracleExtractionConnection(
                row_count=2,
                sample_rows=[(1, "a@example.internal"), (2, "b@example.internal")],
                sample_columns=("CUSTOMER_ID", "EMAIL"),
                table_columns=("CUSTOMER_ID", "EMAIL"),
                pk_columns=("CUSTOMER_ID",),
                executed=executed,
            ),
        )
        # use missing table columns on second table through metadata mismatch
        adapter._metadata_catalog = InMemoryMetadataCatalogRepository(
            oracle_metadata_objects(),
            oracle_relationships(),
        )

        # cleanup path already exercised by general exception branch via bad query config
        # create a dedicated failing adapter instead
        failing_adapter = OracleBaselineRefreshPipelineAdapter(
            metadata_catalog=InMemoryMetadataCatalogRepository(
                oracle_metadata_objects(),
                oracle_relationships(),
            ),
            data_sources=InMemoryDataSourceRepository([sample_oracle_source()]),
            connect=lambda _endpoint: OracleExtractionConnection(
                row_count=2,
                sample_rows=[(1, "a@example.internal"), (2, "b@example.internal")],
                sample_columns=("CUSTOMER_ID", "EMAIL"),
                table_columns=("CUSTOMER_ID", "EMAIL"),
                pk_columns=("CUSTOMER_ID",),
                executed=executed,
            ),
            artifact_dir=artifact_dir,
            clock=FakeClock(),
        )
        failing_adapter._order_tables = lambda **kwargs: [  # type: ignore[method-assign]
            oracle_metadata_objects()[0],
            oracle_metadata_objects()[1],
        ]
        calls = {"count": 0}
        original_execute = failing_adapter._extraction.execute
        def flaky_execute(*, job, plan):
            calls["count"] += 1
            if calls["count"] == 2:
                raise DomainError("forced refresh failure")
            return original_execute(job=job, plan=plan)
        failing_adapter._extraction.execute = flaky_execute  # type: ignore[assignment]

        with pytest.raises(DomainError, match="forced refresh failure"):
            failing_adapter.execute(
                job=refresh_job(),
                source=sample_oracle_source(),
                profile=sample_profile(),
                existing_baseline=None,
            )

        assert os.listdir(artifact_dir) == []
