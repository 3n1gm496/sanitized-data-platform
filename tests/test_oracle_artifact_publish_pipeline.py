from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import tempfile

import pytest

from sanitized_data_platform.adapters.oracle.artifact_publish_pipeline import (
    OracleArtifactPublishPipelineAdapter,
)
from sanitized_data_platform.domain.entities import ArtifactPublishJob
from sanitized_data_platform.domain.enums import DatabaseEngine, ExtractionArtifactFormat
from sanitized_data_platform.domain.errors import DomainError

from tests.fakes import sample_extraction_artifact
from tests.oracle_helpers import OraclePublishConnection, sample_oracle_target


def artifact_publish_job() -> ArtifactPublishJob:
    return ArtifactPublishJob.create(
        job_id="artifact-publish-job-1",
        extraction_artifact_id="extraction-artifact-1",
        source_id="source-crm-oracle",
        root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
        target_environment_id="env-dev",
        requested_by="developer@example.internal",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_oracle_artifact_publish_pipeline_imports_jsonl_into_target_table():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    connection = OraclePublishConnection(executed, {"CRM.CUSTOMERS": ("CUSTOMER_ID", "EMAIL")})
    adapter = OracleArtifactPublishPipelineAdapter(connect=lambda _endpoint: connection)
    payload = (
        '{"CUSTOMER_ID": 1, "EMAIL": "a@example.internal"}\n'
        '{"CUSTOMER_ID": 2, "EMAIL": "b@example.internal"}\n'
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write(payload)
        handle.flush()
        artifact = replace(
            sample_extraction_artifact(),
            source_id="source-crm-oracle",
            root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
            artifact_path=handle.name,
            row_count=2,
            checksum=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        )

        summary = adapter.execute(
            job=artifact_publish_job(),
            artifact=artifact,
            target=sample_oracle_target(),
        )

    assert summary["deliveryStrategy"] == "oracle-jsonl-root-table-import"
    assert summary["targetTable"] == "CRM.CUSTOMERS"
    assert summary["insertedRowCount"] == 2
    assert summary["rowsImported"] == 2
    assert connection.committed is True
    assert executed == [
        (adapter._LIST_TABLE_COLUMNS_SQL, ("CRM", "CUSTOMERS")),
        (
            'INSERT INTO "CRM"."CUSTOMERS" ("CUSTOMER_ID", "EMAIL") VALUES (:1, :2)',
            (1, "a@example.internal"),
        ),
        (
            'INSERT INTO "CRM"."CUSTOMERS" ("CUSTOMER_ID", "EMAIL") VALUES (:1, :2)',
            (2, "b@example.internal"),
        ),
    ]


def test_oracle_artifact_publish_pipeline_rejects_missing_artifact_file():
    adapter = OracleArtifactPublishPipelineAdapter(
        connect=lambda _endpoint: OraclePublishConnection([], {"CRM.CUSTOMERS": ("CUSTOMER_ID", "EMAIL")})
    )
    artifact = replace(
        sample_extraction_artifact(),
        source_id="source-crm-oracle",
        root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
        artifact_path="/tmp/missing-oracle-artifact.jsonl",
    )

    with pytest.raises(DomainError, match="artifact file is missing"):
        adapter.execute(job=artifact_publish_job(), artifact=artifact, target=sample_oracle_target())


def test_oracle_artifact_publish_pipeline_rejects_unsupported_artifact_format():
    adapter = OracleArtifactPublishPipelineAdapter(
        connect=lambda _endpoint: OraclePublishConnection([], {"CRM.CUSTOMERS": ("CUSTOMER_ID", "EMAIL")})
    )
    artifact = replace(
        sample_extraction_artifact(),
        source_id="source-crm-oracle",
        root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
        artifact_format=ExtractionArtifactFormat.CSV,
    )

    with pytest.raises(DomainError, match="supports only JSONL artifacts"):
        adapter.execute(job=artifact_publish_job(), artifact=artifact, target=sample_oracle_target())


def test_oracle_artifact_publish_pipeline_rejects_unsupported_target_engine():
    adapter = OracleArtifactPublishPipelineAdapter(
        connect=lambda _endpoint: OraclePublishConnection([], {"CRM.CUSTOMERS": ("CUSTOMER_ID", "EMAIL")})
    )
    target = replace(sample_oracle_target(), engine_type=DatabaseEngine.POSTGRES)

    with pytest.raises(DomainError, match="can only execute oracle targets"):
        adapter.execute(job=artifact_publish_job(), artifact=replace(
            sample_extraction_artifact(),
            source_id="source-crm-oracle",
            root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
        ), target=target)


def test_oracle_artifact_publish_pipeline_rejects_missing_target_columns():
    adapter = OracleArtifactPublishPipelineAdapter(
        connect=lambda _endpoint: OraclePublishConnection([], {"CRM.CUSTOMERS": ("CUSTOMER_ID",)})
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write('{"CUSTOMER_ID": 1, "EMAIL": "a@example.internal"}\n')
        handle.flush()
        artifact = replace(
            sample_extraction_artifact(),
            source_id="source-crm-oracle",
            root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
            artifact_path=handle.name,
        )

        with pytest.raises(DomainError, match="projection does not match target table columns: EMAIL"):
            adapter.execute(job=artifact_publish_job(), artifact=artifact, target=sample_oracle_target())


def test_oracle_artifact_publish_pipeline_rejects_checksum_mismatch_before_commit():
    connection = OraclePublishConnection([], {"CRM.CUSTOMERS": ("CUSTOMER_ID", "EMAIL")})
    adapter = OracleArtifactPublishPipelineAdapter(connect=lambda _endpoint: connection)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl") as handle:
        handle.write('{"CUSTOMER_ID": 1, "EMAIL": "a@example.internal"}\n')
        handle.flush()
        artifact = replace(
            sample_extraction_artifact(),
            source_id="source-crm-oracle",
            root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
            artifact_path=handle.name,
            row_count=1,
            checksum="wrong-checksum",
        )

        with pytest.raises(DomainError, match="checksum verification failed before commit"):
            adapter.execute(job=artifact_publish_job(), artifact=artifact, target=sample_oracle_target())

    assert connection.committed is False
    assert connection.rolled_back is True
