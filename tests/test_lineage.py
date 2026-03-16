from datetime import datetime, timezone

from sanitized_data_platform.application.services import LineageQueryService
from sanitized_data_platform.domain.entities import LineageRecord

from tests.fakes import InMemoryLineageRepository


def test_lineage_query_service_lists_baseline_lineage():
    repository = InMemoryLineageRepository()
    repository.add(
        LineageRecord(
            record_id="lineage-1",
            source_type="baseline_refresh_job",
            source_id="baseline-refresh-1",
            target_type="sanitized_baseline",
            target_id="baseline-crm-dev-v1",
            event_type="baseline_materialized",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            details={"baselineVersion": "2026.01.01.1"},
        )
    )
    repository.add(
        LineageRecord(
            record_id="lineage-2",
            source_type="validation_report",
            source_id="validation-baseline-crm-dev-v1",
            target_type="sanitized_baseline",
            target_id="baseline-crm-dev-v1",
            event_type="baseline_validated",
            created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            details={"validationStatus": "passed"},
        )
    )

    result = LineageQueryService(repository).get_baseline_lineage("baseline-crm-dev-v1")

    assert result.subject_type == "sanitized_baseline"
    assert result.subject_id == "baseline-crm-dev-v1"
    assert [item.event_type for item in result.items] == [
        "baseline_materialized",
        "baseline_validated",
    ]


def test_lineage_query_service_lists_publish_job_lineage():
    repository = InMemoryLineageRepository()
    repository.add(
        LineageRecord(
            record_id="lineage-1",
            source_type="sanitized_baseline",
            source_id="baseline-crm-dev-v1",
            target_type="publish_job",
            target_id="job-1",
            event_type="baseline_published",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            details={"baselineVersion": "2026.01.01.1"},
        )
    )

    result = LineageQueryService(repository).get_publish_job_lineage("job-1")

    assert result.subject_type == "publish_job"
    assert result.subject_id == "job-1"
    assert result.items[0].source_type == "sanitized_baseline"
    assert result.items[0].event_type == "baseline_published"


def test_lineage_query_service_lists_extraction_job_lineage():
    repository = InMemoryLineageRepository()
    repository.add(
        LineageRecord(
            record_id="lineage-1",
            source_type="data_source",
            source_id="source-crm-replica",
            target_type="extraction_job",
            target_id="extraction-1",
            event_type="extraction_from_source",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            details={"systemId": "crm", "selectedObjectCount": 2},
        )
    )
    repository.add(
        LineageRecord(
            record_id="lineage-2",
            source_type="metadata_object",
            source_id="table-customers",
            target_type="extraction_job",
            target_id="extraction-1",
            event_type="extraction_root_selected",
            created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            details={"includeRelated": True, "maxDepth": 1},
        )
    )

    result = LineageQueryService(repository).get_extraction_job_lineage("extraction-1")

    assert result.subject_type == "extraction_job"
    assert result.subject_id == "extraction-1"
    assert [item.event_type for item in result.items] == [
        "extraction_from_source",
        "extraction_root_selected",
    ]
