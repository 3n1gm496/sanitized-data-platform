from datetime import datetime, timezone
import hashlib
import json
import os
import tempfile

import pytest

from sanitized_data_platform.adapters.postgres.extraction_pipeline import (
    PostgreSQLExtractionPipelineAdapter,
)
from sanitized_data_platform.domain.errors import DomainError
from sanitized_data_platform.domain.entities import (
    ExtractionJob,
    ExtractionPlan,
    ExtractionRoot,
    SelectionCriteria,
    TransformationPolicy,
    TraversalRule,
)
from sanitized_data_platform.domain.enums import ExtractionArtifactKind, TransformationType

from tests.fakes import (
    InMemoryDataSourceRepository,
    InMemoryTransformationPolicyRepository,
    StubTokenVault,
    sample_source,
)


class FakeCursor:
    def __init__(
        self,
        *,
        row_count: int,
        sample_rows: list[tuple[object, ...]],
        sample_columns: tuple[str, ...],
        table_columns: tuple[str, ...],
        pk_columns: tuple[str, ...],
        executed: list[tuple[str, tuple[object, ...] | None]],
    ) -> None:
        self._row_count = row_count
        self._sample_rows = sample_rows
        self._sample_columns = sample_columns
        self._table_columns = table_columns
        self._pk_columns = pk_columns
        self._executed = executed
        self._last_query = ""
        self._row_offset = 0

    def execute(self, query: str, params=None) -> None:
        self._executed.append((query, params))
        self._last_query = query
        self._row_offset = 0

    def fetchone(self) -> tuple[object, ...]:
        return (self._row_count,)

    def fetchall(self) -> list[tuple[object, ...]]:
        if "information_schema.columns" in self._last_query:
            return [(column,) for column in self._table_columns]
        if "constraint_type = 'PRIMARY KEY'" in self._last_query:
            return [(column,) for column in self._pk_columns]
        if "SELECT *" in self._last_query or 'SELECT "' in self._last_query:
            return list(self._sample_rows)
        return []

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        if "SELECT *" not in self._last_query and 'SELECT "' not in self._last_query:
            return []
        start = self._row_offset
        end = min(start + size, len(self._sample_rows))
        self._row_offset = end
        return list(self._sample_rows[start:end])

    @property
    def description(self):
        if "SELECT *" not in self._last_query and 'SELECT "' not in self._last_query:
            return None
        return tuple((column_name,) for column_name in self._sample_columns)

    def close(self) -> None:
        return None


class FakeConnection:
    def __init__(
        self,
        *,
        row_count: int,
        sample_rows: list[tuple[object, ...]],
        sample_columns: tuple[str, ...],
        table_columns: tuple[str, ...],
        pk_columns: tuple[str, ...],
        executed: list[tuple[str, tuple[object, ...] | None]],
    ) -> None:
        self._row_count = row_count
        self._sample_rows = sample_rows
        self._sample_columns = sample_columns
        self._table_columns = table_columns
        self._pk_columns = pk_columns
        self._executed = executed

    def cursor(self) -> FakeCursor:
        return FakeCursor(
            row_count=self._row_count,
            sample_rows=self._sample_rows,
            sample_columns=self._sample_columns,
            table_columns=self._table_columns,
            pk_columns=self._pk_columns,
            executed=self._executed,
        )

    def close(self) -> None:
        return None


def extraction_job() -> ExtractionJob:
    return ExtractionJob.create(
        job_id="extraction-1",
        source_id="source-crm-replica",
        system_id="crm",
        plan_snapshot_id="extraction-plan-snapshot-1",
        root_object_id="table:source-crm-replica:public.customers",
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
        source_id="source-crm-replica",
        root=ExtractionRoot(
            object_id="table:source-crm-replica:public.customers",
            criteria=criteria,
            selected_columns=selected_columns,
            artifact_kind=artifact_kind,
        ),
        traversal_rule=TraversalRule(
            include_related=include_related,
            max_depth=1 if include_related else 0,
        ),
        selected_object_ids=("table:source-crm-replica:public.customers",),
        selected_relationship_ids=(),
    )


def make_adapter(
    *,
    executed: list[tuple[str, tuple[object, ...] | None]],
    row_count: int = 0,
    sample_rows: list[tuple[object, ...]] | None = None,
    sample_columns: tuple[str, ...] = ("customer_id", "email"),
    table_columns: tuple[str, ...] = ("customer_id", "email"),
    pk_columns: tuple[str, ...] = ("customer_id",),
    policies: list[TransformationPolicy] | None = None,
    token_vault=None,
    sample_limit: int = 10,
    artifact_dir: str | None = None,
) -> PostgreSQLExtractionPipelineAdapter:
    return PostgreSQLExtractionPipelineAdapter(
        data_sources=InMemoryDataSourceRepository([sample_source()]),
        policies=InMemoryTransformationPolicyRepository(policies or []),
        token_vault=token_vault,
        sample_limit=sample_limit,
        artifact_dir=artifact_dir,
        connect=lambda _endpoint: FakeConnection(
            row_count=row_count,
            sample_rows=sample_rows or [],
            sample_columns=sample_columns,
            table_columns=table_columns,
            pk_columns=pk_columns,
            executed=executed,
        ),
    )


def test_postgres_extraction_pipeline_executes_projected_sample_query():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=7,
            sample_rows=[(1, "a@example.internal"), (2, "b@example.internal")],
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        assert summary["extractionStrategy"] == "postgres-table-root"
        assert summary["artifactKind"] == "sample"
        assert summary["rootObjectId"] == "table:source-crm-replica:public.customers"
        assert summary["rootTable"] == "public.customers"
        assert summary["selectedColumns"] == ["customer_id", "email"]
        assert summary["sampleOrderedBy"] == ["customer_id"]
        assert summary["sampleOrderingDeterministic"] is True
        assert summary["rowCount"] == 7
        assert summary["rowSampleLimit"] == 10
        assert summary["rowSampleCount"] == 2
        assert summary["rowSample"] == [
            {"customer_id": 1, "email": "a@example.internal"},
            {"customer_id": 2, "email": "b@example.internal"},
        ]
        assert summary["artifactFormat"] == "jsonl"
        assert summary["materializedRowCount"] == 2
        assert os.path.exists(summary["artifactPath"])
        assert summary["artifactFileSizeBytes"] == os.path.getsize(summary["artifactPath"])
        with open(summary["artifactPath"], encoding="utf-8") as artifact_file:
            lines = [json.loads(line) for line in artifact_file if line.strip()]
        with open(summary["artifactPath"], "rb") as artifact_file:
            artifact_bytes = artifact_file.read()
        assert lines == summary["rowSample"]
        assert summary["artifactChecksum"] == hashlib.sha256(artifact_bytes).hexdigest()
        assert summary["artifactColumnCount"] == 2
        assert len(executed) == 4
        assert executed[2][0] == 'SELECT COUNT(*) FROM "public"."customers"'
        assert executed[2][1] == ()
        assert executed[3][0] == (
            'SELECT "customer_id", "email" FROM "public"."customers" '
            'ORDER BY "customer_id" ASC LIMIT %s'
        )
        assert executed[3][1] == (10,)


def test_postgres_extraction_pipeline_materializes_full_root_table_rows():
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
        assert summary["rowSample"] == [
            {"customer_id": 1, "email": "a@example.internal"},
            {"customer_id": 2, "email": "b@example.internal"},
        ]
        assert summary["notes"] == [
            "Full extraction artifact contains all matching rows; inline rowSample is a bounded preview only."
        ]
        assert executed[3][0] == (
            'SELECT "customer_id", "email" FROM "public"."customers" '
            'ORDER BY "customer_id" ASC'
        )
        assert executed[3][1] == ()
        with open(summary["artifactPath"], encoding="utf-8") as artifact_file:
            lines = [json.loads(line) for line in artifact_file if line.strip()]
        with open(summary["artifactPath"], "rb") as artifact_file:
            artifact_bytes = artifact_file.read()
        assert lines == [
            {"customer_id": 1, "email": "a@example.internal"},
            {"customer_id": 2, "email": "b@example.internal"},
            {"customer_id": 3, "email": "c@example.internal"},
        ]
        assert summary["artifactFileSizeBytes"] == os.path.getsize(summary["artifactPath"])
        assert summary["artifactChecksum"] == hashlib.sha256(artifact_bytes).hexdigest()
        assert summary["artifactColumnCount"] == 2


def test_postgres_extraction_pipeline_uses_narrowed_selected_columns_projection():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=2,
            sample_rows=[(1,), (2,)],
            sample_columns=("customer_id",),
            table_columns=("customer_id", "email"),
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(
            job=extraction_job(),
            plan=extraction_plan(selected_columns=("customer_id",)),
        )

        assert summary["selectedColumns"] == ["customer_id"]
        assert summary["rowSample"] == [{"customer_id": 1}, {"customer_id": 2}]
        assert executed[3][0] == (
            'SELECT "customer_id" FROM "public"."customers" '
            'ORDER BY "customer_id" ASC LIMIT %s'
        )
        with open(summary["artifactPath"], encoding="utf-8") as artifact_file:
            lines = [json.loads(line) for line in artifact_file if line.strip()]
        assert lines == summary["rowSample"]


def test_postgres_extraction_pipeline_applies_criteria_with_parameters():
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
                SelectionCriteria(field_name="customer_id", operator="eq", value="42"),
                SelectionCriteria(field_name="email", operator="ilike", value="%@example.com"),
            )
        )

        summary = adapter.execute(job=extraction_job(), plan=plan)

        assert summary["rowCount"] == 2
        assert summary["rowSampleCount"] == 2
        assert summary["materializedRowCount"] == 2
        assert executed[2][0] == (
            'SELECT COUNT(*) FROM "public"."customers" '
            'WHERE "customer_id" = %s AND "email" ILIKE %s'
        )
        assert executed[2][1] == ("42", "%@example.com")
        assert executed[3][0] == (
            'SELECT "customer_id", "email" FROM "public"."customers" '
            'WHERE "customer_id" = %s AND "email" ILIKE %s '
            'ORDER BY "customer_id" ASC LIMIT %s'
        )
        assert executed[3][1] == ("42", "%@example.com", 10)


def test_postgres_extraction_pipeline_keeps_criteria_valid_when_projection_is_narrowed():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=1,
            sample_rows=[("first@example.com",)],
            sample_columns=("email",),
            table_columns=("customer_id", "email"),
            artifact_dir=artifact_dir,
        )
        plan = extraction_plan(
            criteria=(
                SelectionCriteria(field_name="customer_id", operator="eq", value="42"),
            ),
            selected_columns=("email",),
        )

        summary = adapter.execute(job=extraction_job(), plan=plan)

        assert summary["selectedColumns"] == ["email"]
        assert summary["rowSample"] == [{"email": "first@example.com"}]
        assert executed[2][0] == (
            'SELECT COUNT(*) FROM "public"."customers" '
            'WHERE "customer_id" = %s'
        )
        assert executed[3][0] == (
            'SELECT "email" FROM "public"."customers" '
            'WHERE "customer_id" = %s ORDER BY "customer_id" ASC LIMIT %s'
        )


def test_postgres_extraction_pipeline_respects_sample_limit():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=5,
            sample_rows=[(1, "only-one@example.internal")],
            sample_limit=1,
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        assert summary["rowCount"] == 5
        assert summary["rowSampleLimit"] == 1
        assert summary["rowSampleCount"] == 1
        assert summary["materializedRowCount"] == 1
        assert summary["rowSample"] == [
            {"customer_id": 1, "email": "only-one@example.internal"}
        ]
        assert executed[3][1] == (1,)


def test_postgres_extraction_pipeline_falls_back_when_ordering_not_available():
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
        assert "notes" in summary
        assert summary["notes"] == [
            "Deterministic sample ordering not available for this table; sample order may vary."
        ]
        assert executed[3][0] == (
            'SELECT "customer_id", "email" FROM "public"."customers" LIMIT %s'
        )


def test_postgres_extraction_pipeline_marks_include_related_as_not_executed():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=3,
            sample_rows=[(1, "a@example.internal")],
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(
            job=extraction_job(),
            plan=extraction_plan(include_related=True),
        )

        assert summary["rowCount"] == 3
        assert summary["sampleOrderingDeterministic"] is True
        assert summary["notes"] == [
            "include_related is planned but related-table execution is not implemented yet; only root table extracted."
        ]


def test_postgres_extraction_pipeline_applies_irreversible_masking_policy():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-mask-email",
        system_id="crm",
        system_name="CRM",
        object_name="public.customers",
        column_name="email",
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
        assert summary["transformedColumns"] == ["email"]
        assert summary["transformedValueCount"] == 2
        assert summary["unsupportedTransformationTypes"] == []
        assert summary["rowSample"] == [
            {"customer_id": 1, "email": "***MASKED***"},
            {"customer_id": 2, "email": "***MASKED***"},
        ]
        with open(summary["artifactPath"], encoding="utf-8") as artifact_file:
            lines = [json.loads(line) for line in artifact_file if line.strip()]
        assert lines == summary["rowSample"]


def test_postgres_extraction_pipeline_applies_hashing_policy():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-hash-email",
        system_id="crm",
        system_name="CRM",
        object_name="public.customers",
        column_name="email",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.HASHING,
    )
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=1,
            sample_rows=[(7, "hash-me@example.internal")],
            policies=[policy],
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        expected_hash = hashlib.sha256("hash-me@example.internal".encode("utf-8")).hexdigest()
        assert summary["transformationsApplied"] is True
        assert summary["rowSample"] == [{"customer_id": 7, "email": expected_hash}]
        assert summary["transformedColumns"] == ["email"]
        assert summary["transformedValueCount"] == 1


def test_postgres_extraction_pipeline_applies_deterministic_pseudonymization_repeatably():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-dp-email",
        system_id="crm",
        system_name="CRM",
        object_name="public.customers",
        column_name="email",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.DETERMINISTIC_PSEUDONYMIZATION,
    )
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=3,
            sample_rows=[
                (1, "same@example.internal"),
                (2, "same@example.internal"),
                (3, "different@example.internal"),
            ],
            policies=[policy],
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        rows = summary["rowSample"]
        first_value = rows[0]["email"]
        second_value = rows[1]["email"]
        third_value = rows[2]["email"]
        assert isinstance(first_value, str)
        assert len(first_value) == len("same@example.internal")
        assert first_value.count("@") == 1
        assert first_value.count(".") == 1
        assert first_value.endswith(".internal")
        assert first_value == second_value
        assert first_value != third_value
        assert summary["transformationsApplied"] is True
        assert summary["transformedColumns"] == ["email"]
        assert summary["transformedValueCount"] == 3


def test_postgres_extraction_pipeline_applies_reversible_tokenization_with_token_vault():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-tokenize-email",
        system_id="crm",
        system_name="CRM",
        object_name="public.customers",
        column_name="email",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.REVERSIBLE_TOKENIZATION,
        reversible=True,
        tokenization_domain_id="customer-email",
    )
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=2,
            sample_rows=[(1, "a@example.internal"), (2, "b@example.internal")],
            policies=[policy],
            token_vault=StubTokenVault(),
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        assert summary["transformationsApplied"] is True
        assert summary["unsupportedTransformationTypes"] == []
        assert summary["rowSample"] == [
            {"customer_id": 1, "email": "tok::customer-email::a@example.internal"},
            {"customer_id": 2, "email": "tok::customer-email::b@example.internal"},
        ]


def test_postgres_extraction_pipeline_rejects_reversible_tokenization_without_token_vault():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-tokenize-email",
        system_id="crm",
        system_name="CRM",
        object_name="public.customers",
        column_name="email",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.REVERSIBLE_TOKENIZATION,
        reversible=True,
        tokenization_domain_id="customer-email",
    )
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=1,
            sample_rows=[(1, "a@example.internal")],
            policies=[policy],
            artifact_dir=artifact_dir,
        )

        with pytest.raises(DomainError) as exc:
            adapter.execute(job=extraction_job(), plan=extraction_plan())

        assert str(exc.value) == "Reversible tokenization requires a configured token vault service."


def test_postgres_extraction_pipeline_supports_coexisting_masking_hashing_and_pseudonymization():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policies = [
        TransformationPolicy(
            policy_id="policy-mask-email",
            system_id="crm",
            system_name="CRM",
            object_name="public.customers",
            column_name="email",
            sensitivity_tag="pii.email",
            transformation_type=TransformationType.IRREVERSIBLE_MASKING,
        ),
        TransformationPolicy(
            policy_id="policy-hash-customer-id",
            system_id="crm",
            system_name="CRM",
            object_name="public.customers",
            column_name="customer_id",
            sensitivity_tag="pii.customer_id",
            transformation_type=TransformationType.HASHING,
        ),
        TransformationPolicy(
            policy_id="policy-dp-first-name",
            system_id="crm",
            system_name="CRM",
            object_name="public.customers",
            column_name="first_name",
            sensitivity_tag="pii.name",
            transformation_type=TransformationType.DETERMINISTIC_PSEUDONYMIZATION,
        ),
    ]
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=1,
            sample_rows=[(9, "sample@example.internal", "Ada")],
            sample_columns=("customer_id", "email", "first_name"),
            table_columns=("customer_id", "email", "first_name"),
            policies=policies,
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        row = summary["rowSample"][0]
        assert row["email"] == "***MASKED***"
        assert row["customer_id"] == hashlib.sha256("9".encode("utf-8")).hexdigest()
        assert isinstance(row["first_name"], str)
        assert row["first_name"] != "Ada"
        assert len(row["first_name"]) == len("Ada")
        assert row["first_name"][0].isupper()
        assert row["first_name"][1:].islower()
        assert summary["transformationsApplied"] is True
        assert summary["transformedColumns"] == ["customer_id", "email", "first_name"]
        assert summary["transformedValueCount"] == 3
        with open(summary["artifactPath"], encoding="utf-8") as artifact_file:
            lines = [json.loads(line) for line in artifact_file if line.strip()]
        assert lines == summary["rowSample"]


def test_postgres_extraction_pipeline_leaves_values_unchanged_without_matching_policy():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-for-other-column",
        system_id="crm",
        system_name="CRM",
        object_name="public.customers",
        column_name="first_name",
        sensitivity_tag="pii.name",
        transformation_type=TransformationType.IRREVERSIBLE_MASKING,
    )
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=1,
            sample_rows=[(10, "no-policy@example.internal")],
            policies=[policy],
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        assert summary["transformationsApplied"] is False
        assert summary["transformedColumns"] == []
        assert summary["transformedValueCount"] == 0
        assert summary["rowSample"] == [
            {"customer_id": 10, "email": "no-policy@example.internal"}
        ]


def test_postgres_extraction_pipeline_skips_unsupported_transformation_types_safely():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-unsupported",
        system_id="crm",
        system_name="CRM",
        object_name="public.customers",
        column_name="email",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.SYNTHETIC_REPLACEMENT,
    )
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=1,
            sample_rows=[(12, "unsupported@example.internal")],
            policies=[policy],
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        assert summary["transformationsApplied"] is False
        assert summary["unsupportedTransformationTypes"] == ["synthetic_replacement"]
        assert summary["rowSample"] == [
            {"customer_id": 12, "email": "unsupported@example.internal"}
        ]
        assert "notes" in summary
        assert summary["notes"] == [
            "Unsupported transformation types were skipped: synthetic_replacement"
        ]


def test_postgres_extraction_pipeline_matches_policy_by_canonical_object_id():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-canonical-match",
        system_id="crm",
        system_name="CRM",
        object_name="legacy.not-used",
        object_id="table:source-crm-replica:public.customers",
        column_name="email",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.IRREVERSIBLE_MASKING,
    )
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=1,
            sample_rows=[(20, "canonical@example.internal")],
            policies=[policy],
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        assert summary["transformationsApplied"] is True
        assert summary["rowSample"] == [{"customer_id": 20, "email": "***MASKED***"}]


def test_postgres_extraction_pipeline_keeps_backward_compatible_object_name_matching():
    executed: list[tuple[str, tuple[object, ...] | None]] = []
    policy = TransformationPolicy(
        policy_id="policy-legacy-name",
        system_id="crm",
        system_name="CRM",
        object_name="PUBLIC.CUSTOMERS",
        column_name="email",
        sensitivity_tag="pii.email",
        transformation_type=TransformationType.HASHING,
    )
    with tempfile.TemporaryDirectory() as artifact_dir:
        adapter = make_adapter(
            executed=executed,
            row_count=1,
            sample_rows=[(30, "legacy@example.internal")],
            policies=[policy],
            artifact_dir=artifact_dir,
        )

        summary = adapter.execute(job=extraction_job(), plan=extraction_plan())

        expected_hash = hashlib.sha256("legacy@example.internal".encode("utf-8")).hexdigest()
        assert summary["transformationsApplied"] is True
        assert summary["rowSample"] == [{"customer_id": 30, "email": expected_hash}]
