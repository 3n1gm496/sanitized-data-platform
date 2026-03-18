from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import tempfile

import pytest

from sanitized_data_platform.adapters.oracle.baseline_publish_pipeline import (
    OracleBaselinePublishPipelineAdapter,
)
from sanitized_data_platform.domain.entities import PublishJob
from sanitized_data_platform.domain.errors import DomainError

from tests.fakes import InMemoryBaselineAssetRepository, sample_baseline_asset, sample_profile
from tests.oracle_helpers import (
    OraclePublishConnection,
    sample_oracle_baseline,
    sample_oracle_source,
    sample_oracle_target,
)


def publish_job() -> PublishJob:
    return PublishJob.create(
        job_id="job-1",
        source_id="source-crm-oracle",
        sanitized_baseline_id="baseline-crm-dev-v1",
        baseline_validation_status=None,
        baseline_validation_warning_count=0,
        baseline_validation_error_count=0,
        baseline_validated_at=None,
        target_environment_id="env-dev",
        dataset_profile_id="profile-full-sanitized",
        requested_by="developer@example.internal",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_oracle_baseline_publish_pipeline_imports_materialized_baseline_assets():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    connection = OraclePublishConnection(executed, {"CRM.CUSTOMERS": ("CUSTOMER_ID", "EMAIL")})
    payload = (
        '{"CUSTOMER_ID": 1, "EMAIL": "a@example.internal"}\n'
        '{"CUSTOMER_ID": 2, "EMAIL": "b@example.internal"}\n'
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write(payload)
        handle.flush()
        baseline_assets = InMemoryBaselineAssetRepository(
            [
                replace(
                    sample_baseline_asset(),
                    source_id="source-crm-oracle",
                    root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
                    artifact_path=handle.name,
                    row_count=2,
                    checksum=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                )
            ]
        )
        adapter = OracleBaselinePublishPipelineAdapter(
            baseline_assets=baseline_assets,
            connect=lambda _endpoint: connection,
        )

        summary = adapter.execute(
            job=publish_job(),
            source=sample_oracle_source(),
            baseline=sample_oracle_baseline(),
            target=sample_oracle_target(),
            profile=sample_profile(),
        )

    assert summary["baselineStrategy"] == "oracle-materialized-baseline"
    assert summary["baselineId"] == "baseline-crm-dev-v1"
    assert summary["targetEnvironmentId"] == "env-dev"
    assert summary["importedTableCount"] == 1
    assert summary["importedTables"] == ["CRM.CUSTOMERS"]
    assert summary["rowsPublished"] == 2
    assert connection.committed is True


def test_oracle_baseline_publish_pipeline_rejects_missing_materialized_assets():
    adapter = OracleBaselinePublishPipelineAdapter(
        baseline_assets=InMemoryBaselineAssetRepository(),
        connect=lambda _endpoint: OraclePublishConnection([], {"CRM.CUSTOMERS": ("CUSTOMER_ID", "EMAIL")}),
    )

    with pytest.raises(DomainError, match="No materialized baseline assets are available"):
        adapter.execute(
            job=publish_job(),
            source=sample_oracle_source(),
            baseline=sample_oracle_baseline(),
            target=sample_oracle_target(),
            profile=sample_profile(),
        )


def test_oracle_baseline_publish_pipeline_rejects_checksum_mismatch_before_commit():
    connection = OraclePublishConnection([], {"CRM.CUSTOMERS": ("CUSTOMER_ID", "EMAIL")})
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write('{"CUSTOMER_ID": 1, "EMAIL": "a@example.internal"}\n')
        handle.flush()
        adapter = OracleBaselinePublishPipelineAdapter(
            baseline_assets=InMemoryBaselineAssetRepository(
                [
                    replace(
                        sample_baseline_asset(),
                        source_id="source-crm-oracle",
                        root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
                        artifact_path=handle.name,
                        row_count=1,
                        checksum="wrong-checksum",
                    )
                ]
            ),
            connect=lambda _endpoint: connection,
        )

        with pytest.raises(DomainError, match="Baseline asset checksum verification failed before commit"):
            adapter.execute(
                job=publish_job(),
                source=sample_oracle_source(),
                baseline=sample_oracle_baseline(),
                target=sample_oracle_target(),
                profile=sample_profile(),
            )

    assert connection.committed is False
    assert connection.rolled_back is True
