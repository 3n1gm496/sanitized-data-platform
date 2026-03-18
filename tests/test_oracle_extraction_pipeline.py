from datetime import datetime, timezone
import hashlib
import json
import os
import tempfile

import pytest

from sanitized_data_platform.adapters.oracle.extraction_pipeline import (
    OracleExtractionPipelineAdapter,
)
from sanitized_data_platform.domain.entities import (
    ExtractionJob,
    ExtractionPlan,
    ExtractionRoot,
    SelectionCriteria,
    TransformationPolicy,
    TraversalRule,
)
from sanitized_data_platform.domain.enums import (
    ExtractionArtifactKind,
    TransformationType,
)
from sanitized_data_platform.domain.errors import DomainError

from tests.fakes import InMemoryDataSourceRepository, InMemoryTransformationPolicyRepository, StubTokenVault
from tests.oracle_helpers import OracleExtractionConnection, sample_oracle_source


def extraction_job() -> ExtractionJob:
    return ExtractionJob.create(
        job_id="extraction-1",
        source_id="source-crm-oracle",
        system_id="crm",
        plan_snapshot_id="extraction-plan-snapshot-1",
        root_object_id="table:source-crm-oracle:CRM.CUSTOMERS",
        criteria=(),
        include_related=False,
        max_depth=0,
        requested_by="developer@example.internal",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def extraction_plan(
    *,
    include_related: bool = False,
    criteria: tuple[SelectionCriteria, ...] = (),
    selected_columns: tuple[str, ...] = (),
    artifact_kind: ExtractionArtifactKind = ExtractionArtifactKind.SAMPLE,
) -> ExtractionPlan:
    return ExtractionPlan(
        source_id="source-crm-oracle",
        root=ExtractionRoot(
            object_id="table:source-crm-oracle:CRM.CUSTOMERS",
            criteria=criteria,
            selected_columns=selected_columns,
            artifact_kind=artifact_kind,
        ),
        traversal_rule=TraversalRule(
            include_related=include_related,
            max_depth=1 if include_related else 0,
        ),
        selected_object_ids=("table:source-crm-oracle:CRM.CUSTOMERS",),
        selected_relationship_ids=(),
    )


def make_adapter(
    *,
    executed: list[tuple[str, tuple[object, ...] | None]],
    row_count: int = 0,
    sample_rows: list[tuple[object, ...]] | None = None,
    sample_columns: tuple[str, ...] = ("CUSTOMER_ID", "EMAIL"),
    table_columns: tuple[str, ...] = ("CUSTOMER_ID", "EMAIL"),
    pk_columns: tuple[str, ...] = ("CUSTOMER_ID",),
    policies: list[TransformationPolicy] | None = None,
    token_vault=None,
    sample_limit: int = 10,
    artifact_dir: str | None = None,
) -> OracleExtractionPipelineAdapter:
    return OracleExtractionPipelineAdapter(
        data_sources=InMemoryDataSourceRepository([sample_oracle_source()]),
        policies=InMemoryTransformationPolicyRepository(policies or []),
        token_vault=token_vault,
        sample_limit=sample_limit,
        artifact_dir=artifact_dir,
        connect=lambda _endpoint: OracleExtractionConnection(
            row_count=row_count,
            sample_rows=sample_rows or [],
            sample_columns=sample_columns,
            table_columns=table_columns,
            pk_columns=pk_columns,
            executed=executed,
        ),
    )


def test_oracle_extraction_pipeline_executes_projected_sample_query():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=7,
            sample_rows=[(1, "a@example.internal"), (2, "b@example.internal")],
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        assert summary["extractionStrategy"] == "oracle-table-root"
        assert summary["artifactKind"] == "sample"
        assert summary["rootObjectId"] == "table:source-crm-oracle:CRM.CUSTOMERS"
        assert summary["rootTable"] == "CRM.CUSTOMERS"
        assert summary["selectedColumns"] == ["CUSTOMER_ID", "EMAIL"]
        assert summary["sampleOrderedBy"] == ["CUSTOMER_ID"]
        assert summary["sampleOrderingDeterministic"] is True
        assert summary["rowCount"] == 7
        assert summary["rowSampleLimit"] == 10
        assert summary["rowSampleCount"] == 2
        assert summary["rowSample"] == [
            {"CUSTOMER_ID": 1, "EMAIL": "a@example.internal"},
            {"CUSTOMER_ID": 2, "EMAIL": "b@example.internal"},
        ]
        assert summary["artifactFormat"] == "jsonl"
        assert summary["materializedRowCount"] == 2
        assert os.path.exists(summary["artifactPath"])
        assert executed[2][0] == 'SELECT COUNT(*) FROM "CRM"."CUSTOMERS"'
        assert executed[2][1] == ()
        assert executed[3][0] == (
            'SELECT "CUSTOMER_ID", "EMAIL" FROM "CRM"."CUSTOMERS" '
            'ORDER BY "CUSTOMER_ID" ASC FETCH FIRST :1 ROWS ONLY'
        )
        assert executed[3][1] == (10,)


def test_oracle_extraction_pipeline_materializes_full_root_table_rows():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=3,
            sample_limit=2,
            sample_rows=[
                (1, "a@example.internal"),
                (2, "b@example.internal"),
                (3, "c@example.internal"),
            ],
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(
            job=extraction_job(),
            plan=extraction_plan(artifact_kind=ExtractionArtifactKind.FULL),
        )

        assert summary["artifactKind"] == "full"
        assert summary["rowCount"] == 3
        assert summary["rowSampleLimit"] == 2
        assert summary["rowSampleCount"] == 2
        assert summary["materializedRowCount"] == 3
        assert summary["artifactContainsFullResult"] is True
        assert summary["notes"] == [
            "Full extraction artifact contains all matching rows; inline rowSample is a bounded preview only."
        ]
        assert executed[3][0] == (
            'SELECT "CUSTOMER_ID", "EMAIL" FROM "CRM"."CUSTOMERS" '
            'ORDER BY "CUSTOMER_ID" ASC'
        )
        with open(summary["artifactPath"], encoding="utf-8") as artifact_file:
            lines = [json.loads(line) for line in artifact_file if line.strip()]
        assert lines == [
            {"CUSTOMER_ID": 1, "EMAIL": "a@example.internal"},
            {"CUSTOMER_ID": 2, "EMAIL": "b@example.internal"},
            {"CUSTOMER_ID": 3, "EMAIL": "c@example.internal"},
        ]


def test_oracle_extraction_pipeline_uses_narrowed_selected_columns_projection():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=2,
            sample_rows=[(1,), (2,)],
            sample_columns=("CUSTOMER_ID",),
            table_columns=("CUSTOMER_ID", "EMAIL"),
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(
            job=extraction_job(),
            plan=extraction_plan(selected_columns=("CUSTOMER_ID",)),
        )

        assert summary["selectedColumns"] == ["CUSTOMER_ID"]
        assert summary["rowSample"] == [{"CUSTOMER_ID": 1}, {"CUSTOMER_ID": 2}]
        assert executed[3][0] == (
            'SELECT "CUSTOMER_ID" FROM "CRM"."CUSTOMERS" '
            'ORDER BY "CUSTOMER_ID" ASC FETCH FIRST :1 ROWS ONLY'
        )


def test_oracle_extraction_pipeline_applies_criteria_with_parameters():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=2,
            sample_rows=[("42", "first@example.com"), ("43", "second@example.com")],
            artifact_dir=artifact_dir,
        )
        plan = extraction_plan(
            criteria=(
                SelectionCriteria(field_name="CUSTOMER_ID", operator="eq", value="42"),
                SelectionCriteria(field_name="EMAIL", operator="ilike", value="%@example.com"),
            )
        )

        summary = adapter.execute(job=extraction_job(), plan=plan)

        assert summary["rowCount"] == 2
        assert executed[2][0] == (
            'SELECT COUNT(*) FROM "CRM"."CUSTOMERS" '
            'WHERE "CUSTOMER_ID" = :1 AND UPPER("EMAIL") LIKE UPPER(:2)'
        )
        assert executed[2][1] == ("42", "%@example.com")
        assert executed[3][0] == (
            'SELECT "CUSTOMER_ID", "EMAIL" FROM "CRM"."CUSTOMERS" '
            'WHERE "CUSTOMER_ID" = :1 AND UPPER("EMAIL") LIKE UPPER(:2) '
            'ORDER BY "CUSTOMER_ID" ASC FETCH FIRST :3 ROWS ONLY'
        )
        assert executed[3][1] == ("42", "%@example.com", 10)


def test_oracle_extraction_pipeline_falls_back_when_ordering_not_available():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=3,
            sample_rows=[(3, "c@example.internal"), (1, "a@example.internal")],
            pk_columns=(),
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        assert summary["sampleOrderedBy"] is None
        assert summary["sampleOrderingDeterministic"] is False
        assert summary["notes"] == [
            "Deterministic sample ordering not available for this table; sample order may vary."
        ]
        assert executed[3][0] == (
            'SELECT "CUSTOMER_ID", "EMAIL" FROM "CRM"."CUSTOMERS" FETCH FIRST :1 ROWS ONLY'
        )


def test_oracle_extraction_pipeline_applies_masking_policy():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-mask-email",
        system_id="crm",
        system_name="CRM",
        object_name="CRM.CUSTOMERS",
        column_name="EMAIL",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.IRREVERSIBLE_MASKING,
    )
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=2,
            sample_rows=[(1, "a@example.internal"), (2, "b@example.internal")],
            policies=[policy],
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        assert summary["transformationsApplied"] is True
        assert summary["transformedColumns"] == ["EMAIL"]
        assert summary["transformedValueCount"] == 2
        assert summary["rowSample"] == [
            {"CUSTOMER_ID": 1, "EMAIL": "***MASKED***"},
            {"CUSTOMER_ID": 2, "EMAIL": "***MASKED***"},
        ]


def test_oracle_extraction_pipeline_applies_reversible_tokenization_with_token_vault():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-token-email",
        system_id="crm",
        system_name="CRM",
        object_name="CRM.CUSTOMERS",
        column_name="EMAIL",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.REVERSIBLE_TOKENIZATION,
        tokenization_domain_id="crm:CRM.CUSTOMERS.EMAIL",
    )
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=1,
            sample_rows=[(1, "token@example.internal")],
            policies=[policy],
            token_vault=StubTokenVault(),
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        assert summary["rowSample"] == [
            {
                "CUSTOMER_ID": 1,
                "EMAIL": "tok::crm:CRM.CUSTOMERS.EMAIL::token@example.internal",
            }
        ]


def test_oracle_extraction_pipeline_rejects_reversible_tokenization_without_token_vault():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-token-email",
        system_id="crm",
        system_name="CRM",
        object_name="CRM.CUSTOMERS",
        column_name="EMAIL",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.REVERSIBLE_TOKENIZATION,
        tokenization_domain_id="crm:CRM.CUSTOMERS.EMAIL",
    )
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=1,
            sample_rows=[(1, "token@example.internal")],
            policies=[policy],
            artifact_dir=artifact_dir,
        )

        with pytest.raises(DomainError, match="token vault"):
            adapter.execute(job=extraction_job(), plan=extraction_plan())
