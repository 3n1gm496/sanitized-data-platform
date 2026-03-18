from sanitized_data_platform.adapters.registry import AdapterRegistry
from sanitized_data_platform.application.services import EngineCapabilityQueryService
from sanitized_data_platform.domain.enums import DatabaseEngine
from sanitized_data_platform.domain.errors import DomainError


def test_engine_capability_service_lists_registered_engines():
    registry = AdapterRegistry()
    registry.register(
        engine_type=DatabaseEngine.POSTGRES,
        metadata_discovery=object(),
        extraction_pipeline=object(),
        artifact_publish_pipeline=object(),
        baseline_refresh_pipeline=object(),
        baseline_publish_pipeline=object(),
    )
    registry.register(
        engine_type=DatabaseEngine.ORACLE,
        metadata_discovery=object(),
        extraction_pipeline=object(),
        artifact_publish_pipeline=object(),
        baseline_refresh_pipeline=object(),
    )
    service = EngineCapabilityQueryService(registry)

    listing = service.list_engine_capabilities()

    assert [item.engine_type for item in listing.items] == ["oracle", "postgres"]
    assert listing.items[0].release_ready is False
    assert listing.items[1].release_ready is True


def test_engine_capability_service_reads_single_engine():
    registry = AdapterRegistry()
    registry.register(
        engine_type=DatabaseEngine.ORACLE,
        metadata_discovery=object(),
        extraction_pipeline=object(),
        artifact_publish_pipeline=object(),
        baseline_refresh_pipeline=object(),
        baseline_publish_pipeline=object(),
    )
    service = EngineCapabilityQueryService(registry)

    capability = service.get_engine_capability("oracle")

    assert capability.engine_type == "oracle"
    assert capability.release_ready is True
    assert capability.artifact_publish_supported is True


def test_engine_capability_service_rejects_unknown_engine():
    service = EngineCapabilityQueryService(AdapterRegistry())

    try:
        service.get_engine_capability("sqlserver")
    except DomainError as exc:
        assert "No runtime adapter set registered" in str(exc)
    else:
        raise AssertionError("Expected engine capability lookup to fail.")
