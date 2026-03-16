from dataclasses import replace

from sanitized_data_platform.application.services import (
    BaselineEligibilityExplanationService,
    BaselineQueryService,
)
from sanitized_data_platform.domain.enums import BaselineStatus, ValidationStatus

from tests.fakes import (
    InMemoryBaselineRepository,
    InMemorySystemRepository,
    InMemoryValidationRepository,
    PublishValidationSummaryService,
    ValidationLookupService,
    sample_baseline,
    sample_system,
    sample_validation_report,
)


def build_service(*, baselines=None, validation_reports=None):
    return BaselineQueryService(
        systems=InMemorySystemRepository([sample_system()]),
        baselines=InMemoryBaselineRepository(
            [sample_baseline()] if baselines is None else baselines
        ),
        validations=ValidationLookupService(
            InMemoryValidationRepository(
                [sample_validation_report()]
                if validation_reports is None
                else validation_reports
            )
        ),
        validation_summary=PublishValidationSummaryService(),
        eligibility=BaselineEligibilityExplanationService(),
    )


def test_baseline_query_lists_baselines_with_eligibility_and_validation_summary():
    service = build_service()

    result = service.list_baselines(system_id="crm")

    assert result.filters == {"systemId": "crm"}
    assert len(result.items) == 1
    assert result.items[0].baseline_id == "baseline-crm-dev-v1"
    assert result.items[0].publish_eligible is True
    assert result.items[0].eligibility.reason == "eligible"
    assert result.items[0].validation_summary is not None
    assert result.items[0].validation_summary.status == "passed"


def test_baseline_query_reads_baseline_detail_with_eligibility():
    service = build_service()

    result = service.get_baseline("baseline-crm-dev-v1")

    assert result.baseline_id == "baseline-crm-dev-v1"
    assert result.system_id == "crm"
    assert result.publish_eligible is True
    assert result.eligibility.reason == "eligible"
    assert result.validation_summary is not None
    assert result.validation_summary.error_count == 0


def test_baseline_query_explains_missing_validation_report():
    service = build_service(validation_reports=[])

    result = service.get_baseline("baseline-crm-dev-v1")

    assert result.publish_eligible is False
    assert result.eligibility.reason == "missing_validation_report"
    assert result.validation_summary is None


def test_baseline_query_explains_failed_validation():
    service = build_service(
        validation_reports=[
            sample_validation_report(status=ValidationStatus.FAILED)
        ]
    )

    result = service.get_baseline("baseline-crm-dev-v1")

    assert result.publish_eligible is False
    assert result.eligibility.reason == "validation_not_eligible"
    assert result.validation_summary is not None
    assert result.validation_summary.status == "failed"


def test_baseline_query_explains_inactive_baseline_status():
    inactive = replace(
        sample_baseline(),
        status=BaselineStatus.DEPRECATED,
    )
    service = build_service(baselines=[inactive], validation_reports=[])

    result = service.get_baseline("baseline-crm-dev-v1")

    assert result.publish_eligible is False
    assert result.eligibility.reason == "baseline_not_active"


def test_baseline_eligibility_service_can_explain_compatibility_mismatch():
    baseline = sample_baseline()
    report = sample_validation_report()
    explanation = BaselineEligibilityExplanationService().explain(
        baseline,
        report,
        compatibility_mismatch=True,
    )

    assert explanation.eligible is False
    assert explanation.reason == "compatibility_mismatch"
