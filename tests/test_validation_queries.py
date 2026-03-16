from sanitized_data_platform.application.services import (
    ValidationLookupService,
    ValidationQueryService,
)

from tests.fakes import (
    InMemoryBaselineRepository,
    InMemoryValidationRepository,
    sample_baseline,
    sample_validation_report,
)


def test_validation_query_service_reads_validation_report_for_baseline():
    service = ValidationQueryService(
        baselines=InMemoryBaselineRepository([sample_baseline()]),
        validations=ValidationLookupService(
            InMemoryValidationRepository([sample_validation_report()])
        ),
    )

    result = service.get_validation_report_for_baseline("baseline-crm-dev-v1")

    assert result.baseline_id == "baseline-crm-dev-v1"
    assert result.report_id == "validation-baseline-crm-dev-v1"
    assert result.status == "passed"
    assert result.publish_eligible is True


def test_validation_query_service_exposes_check_level_visibility():
    service = ValidationQueryService(
        baselines=InMemoryBaselineRepository([sample_baseline()]),
        validations=ValidationLookupService(
            InMemoryValidationRepository([sample_validation_report()])
        ),
    )

    result = service.get_validation_report_for_baseline("baseline-crm-dev-v1")

    assert len(result.checks) == 1
    assert result.checks[0].check_name == "referential_integrity"
    assert result.checks[0].severity == "info"
    assert result.checks[0].passed is True
