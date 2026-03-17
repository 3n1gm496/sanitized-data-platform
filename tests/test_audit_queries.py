from datetime import datetime, timezone

from sanitized_data_platform.application.services import AuditQueryService
from sanitized_data_platform.domain.entities import AuditEvent

from tests.fakes import InMemoryAuditEventRepository


def test_audit_query_service_lists_events_for_subject_in_time_order():
    repository = InMemoryAuditEventRepository()
    repository.add(
        AuditEvent(
            event_id="audit-2",
            event_type="publish_job_completed",
            actor="developer@example.internal",
            subject_type="publish_job",
            subject_id="job-1",
            details={"rowsPublished": 10},
            created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        )
    )
    repository.add(
        AuditEvent(
            event_id="audit-1",
            event_type="publish_job_requested",
            actor="developer@example.internal",
            subject_type="publish_job",
            subject_id="job-1",
            details={},
            created_at=datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
        )
    )

    result = AuditQueryService(repository).list_events_for_subject("job-1")

    assert [item.event_type for item in result] == [
        "publish_job_requested",
        "publish_job_completed",
    ]
    assert result[0].subject_type == "publish_job"
