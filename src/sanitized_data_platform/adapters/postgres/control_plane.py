from __future__ import annotations

import json
import types
from contextlib import closing
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar, Union, get_args, get_origin, get_type_hints

from sanitized_data_platform.domain.entities import (
    ArtifactPublishJob,
    AuditEvent,
    BaselineRefreshJob,
    BaselineRefreshSchedule,
    BaselineTableAsset,
    DataSource,
    DatasetProfile,
    ExtractionArtifact,
    ExtractionJob,
    ExtractionPlanSnapshot,
    LineageRecord,
    MetadataObject,
    PublishJob,
    Relationship,
    SanitizedBaseline,
    SensitivityTag,
    System,
    TargetEnvironment,
    TransformationPolicy,
    ValidationReport,
)
from sanitized_data_platform.domain.enums import MetadataObjectType
from sanitized_data_platform.domain.errors import DomainError


class SqlBackend(Protocol):
    placeholder: str

    def connect(self): ...


class PsycopgBackend:
    placeholder = "%s"

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is required for PostgreSQL control-plane persistence."
            ) from exc
        return psycopg.connect(self._dsn)


class SqliteBackend:
    placeholder = "?"

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def connect(self):
        import sqlite3

        connection = sqlite3.connect(self._dsn)
        connection.row_factory = sqlite3.Row
        return connection


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return {"__kind__": "datetime", "value": value.isoformat()}
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _serialize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _deserialize(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    if tp is Any:
        if isinstance(value, dict) and value.get("__kind__") == "datetime":
            return datetime.fromisoformat(value["value"])
        if isinstance(value, list):
            return [_deserialize(Any, item) for item in value]
        if isinstance(value, dict):
            return {key: _deserialize(Any, item) for key, item in value.items()}
        return value

    origin = get_origin(tp)
    if origin is not None:
        if origin in (list, tuple):
            args = get_args(tp)
            item_type = args[0] if args else Any
            items = [_deserialize(item_type, item) for item in value]
            return tuple(items) if origin is tuple else items
        if origin is dict:
            args = get_args(tp)
            value_type = args[1] if len(args) > 1 else Any
            return {key: _deserialize(value_type, item) for key, item in value.items()}
        if origin in (Union, types.UnionType):
            args = [arg for arg in get_args(tp) if arg is not type(None)]
            for arg in args:
                try:
                    return _deserialize(arg, value)
                except Exception:
                    continue
            return value

    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(value)
    if tp is datetime:
        if isinstance(value, dict) and value.get("__kind__") == "datetime":
            return datetime.fromisoformat(value["value"])
        return datetime.fromisoformat(value)
    if isinstance(tp, type) and is_dataclass(tp):
        hints = get_type_hints(tp)
        kwargs = {}
        for field in fields(tp):
            field_type = hints.get(field.name, Any)
            kwargs[field.name] = _deserialize(field_type, value[field.name])
        return tp(**kwargs)
    return value


class ControlPlaneJsonStore:
    def __init__(self, backend: SqlBackend) -> None:
        self._backend = backend

    def run_migrations(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS control_plane_records (
                kind TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (kind, entity_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_control_plane_records_kind
            ON control_plane_records(kind)
            """,
            """
            CREATE TABLE IF NOT EXISTS job_leases (
                lease_kind TEXT NOT NULL,
                job_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                claimed_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                lease_expires_at TEXT NOT NULL,
                PRIMARY KEY (lease_kind, job_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_job_leases_expires_at
            ON job_leases(lease_expires_at)
            """,
        )
        self._execute_script(statements)

    def ping(self) -> bool:
        with closing(self._backend.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            cursor.close()
            return row is not None

    def upsert_entity(self, *, kind: str, entity_id: str, payload: dict[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        existing = self.get_entity_payload(kind=kind, entity_id=entity_id)
        created_at = now if existing is None else existing["created_at"]
        statement = f"""
            INSERT INTO control_plane_records (kind, entity_id, payload, created_at, updated_at)
            VALUES ({self._backend.placeholder}, {self._backend.placeholder}, {self._backend.placeholder},
                    {self._backend.placeholder}, {self._backend.placeholder})
            ON CONFLICT(kind, entity_id) DO UPDATE SET
                payload = excluded.payload,
                updated_at = excluded.updated_at
        """
        encoded = json.dumps(payload, sort_keys=True)
        with closing(self._backend.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(
                statement,
                (kind, entity_id, encoded, created_at, now),
            )
            connection.commit()
            cursor.close()

    def delete_entity(self, *, kind: str, entity_id: str) -> None:
        statement = (
            f"DELETE FROM control_plane_records WHERE kind = {self._backend.placeholder} "
            f"AND entity_id = {self._backend.placeholder}"
        )
        with closing(self._backend.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (kind, entity_id))
            connection.commit()
            cursor.close()

    def get_entity_payload(self, *, kind: str, entity_id: str) -> dict[str, Any] | None:
        statement = (
            f"SELECT entity_id, payload, created_at, updated_at FROM control_plane_records "
            f"WHERE kind = {self._backend.placeholder} AND entity_id = {self._backend.placeholder}"
        )
        with closing(self._backend.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (kind, entity_id))
            row = cursor.fetchone()
            cursor.close()
        if row is None:
            return None
        payload = row[1] if not isinstance(row, dict) else row["payload"]
        created_at = row[2] if not isinstance(row, dict) else row["created_at"]
        updated_at = row[3] if not isinstance(row, dict) else row["updated_at"]
        return {
            "payload": json.loads(payload),
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def list_entity_payloads(self, *, kind: str) -> list[dict[str, Any]]:
        statement = (
            f"SELECT entity_id, payload, created_at, updated_at FROM control_plane_records "
            f"WHERE kind = {self._backend.placeholder}"
        )
        with closing(self._backend.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (kind,))
            rows = cursor.fetchall()
            cursor.close()
        records = []
        for row in rows:
            payload = row[1] if not isinstance(row, dict) else row["payload"]
            created_at = row[2] if not isinstance(row, dict) else row["created_at"]
            updated_at = row[3] if not isinstance(row, dict) else row["updated_at"]
            records.append(
                {
                    "payload": json.loads(payload),
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        return records

    def _execute_script(self, statements: tuple[str, ...]) -> None:
        with closing(self._backend.connect()) as connection:
            cursor = connection.cursor()
            for statement in statements:
                cursor.execute(statement)
            connection.commit()
            cursor.close()

    def try_acquire_lease(
        self,
        *,
        lease_kind: str,
        job_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        expires_at = now.replace(microsecond=0).timestamp() + lease_seconds
        expires_at_iso = datetime.fromtimestamp(expires_at, tz=UTC).isoformat()
        delete_statement = (
            f"DELETE FROM job_leases WHERE lease_kind = {self._backend.placeholder} "
            f"AND job_id = {self._backend.placeholder} "
            f"AND lease_expires_at <= {self._backend.placeholder}"
        )
        insert_statement = f"""
            INSERT INTO job_leases (
                lease_kind, job_id, worker_id, claimed_at, heartbeat_at, lease_expires_at
            ) VALUES (
                {self._backend.placeholder},
                {self._backend.placeholder},
                {self._backend.placeholder},
                {self._backend.placeholder},
                {self._backend.placeholder},
                {self._backend.placeholder}
            )
            ON CONFLICT(lease_kind, job_id) DO NOTHING
        """
        with closing(self._backend.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(delete_statement, (lease_kind, job_id, now_iso))
            cursor.execute(
                insert_statement,
                (lease_kind, job_id, worker_id, now_iso, now_iso, expires_at_iso),
            )
            acquired = cursor.rowcount == 1
            connection.commit()
            cursor.close()
        return acquired

    def heartbeat_lease(
        self,
        *,
        lease_kind: str,
        job_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        expires_at_iso = datetime.fromtimestamp(
            now.replace(microsecond=0).timestamp() + lease_seconds,
            tz=UTC,
        ).isoformat()
        statement = (
            f"UPDATE job_leases SET heartbeat_at = {self._backend.placeholder}, "
            f"lease_expires_at = {self._backend.placeholder} "
            f"WHERE lease_kind = {self._backend.placeholder} "
            f"AND job_id = {self._backend.placeholder} "
            f"AND worker_id = {self._backend.placeholder}"
        )
        with closing(self._backend.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (now_iso, expires_at_iso, lease_kind, job_id, worker_id))
            connection.commit()
            cursor.close()

    def release_lease(self, *, lease_kind: str, job_id: str) -> None:
        statement = (
            f"DELETE FROM job_leases WHERE lease_kind = {self._backend.placeholder} "
            f"AND job_id = {self._backend.placeholder}"
        )
        with closing(self._backend.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (lease_kind, job_id))
            connection.commit()
            cursor.close()

    def count_active_leases(self, *, lease_kind: str | None = None) -> int:
        now_iso = datetime.now(UTC).isoformat()
        if lease_kind is None:
            statement = (
                f"SELECT COUNT(*) FROM job_leases WHERE lease_expires_at > {self._backend.placeholder}"
            )
            params = (now_iso,)
        else:
            statement = (
                f"SELECT COUNT(*) FROM job_leases WHERE lease_kind = {self._backend.placeholder} "
                f"AND lease_expires_at > {self._backend.placeholder}"
            )
            params = (lease_kind, now_iso)
        with closing(self._backend.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(statement, params)
            row = cursor.fetchone()
            cursor.close()
        return int(row[0] if row is not None else 0)

    def has_active_lease(self, *, lease_kind: str, job_id: str) -> bool:
        now_iso = datetime.now(UTC).isoformat()
        statement = (
            f"SELECT COUNT(*) FROM job_leases WHERE lease_kind = {self._backend.placeholder} "
            f"AND job_id = {self._backend.placeholder} "
            f"AND lease_expires_at > {self._backend.placeholder}"
        )
        with closing(self._backend.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (lease_kind, job_id, now_iso))
            row = cursor.fetchone()
            cursor.close()
        return bool(row and int(row[0]) > 0)


T = TypeVar("T")


class JsonEntityRepository(Generic[T]):
    def __init__(
        self,
        *,
        store: ControlPlaneJsonStore,
        kind: str,
        entity_type: type[T],
        id_field: str,
    ) -> None:
        self._store = store
        self._kind = kind
        self._entity_type = entity_type
        self._id_field = id_field

    def save_entity(self, entity: T) -> None:
        self._store.upsert_entity(
            kind=self._kind,
            entity_id=getattr(entity, self._id_field),
            payload=_serialize(entity),
        )

    def get_entity(self, entity_id: str) -> T | None:
        record = self._store.get_entity_payload(kind=self._kind, entity_id=entity_id)
        if record is None:
            return None
        return _deserialize(self._entity_type, record["payload"])

    def list_entities(self) -> list[T]:
        return [
            _deserialize(self._entity_type, record["payload"])
            for record in self._store.list_entity_payloads(kind=self._kind)
        ]

    def delete_entity(self, entity_id: str) -> None:
        self._store.delete_entity(kind=self._kind, entity_id=entity_id)


class PostgresSystemRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(store=store, kind="system", entity_type=System, id_field="system_id")

    def list_active(self) -> list[System]:
        return [item for item in self._repo.list_entities() if item.active]

    def get_by_id(self, system_id: str) -> System | None:
        return self._repo.get_entity(system_id)

    def save(self, system: System) -> None:
        self._repo.save_entity(system)


class PostgresDataSourceRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(store=store, kind="data_source", entity_type=DataSource, id_field="source_id")

    def list_active(self) -> list[DataSource]:
        return [item for item in self._repo.list_entities() if item.active]

    def get_by_id(self, source_id: str) -> DataSource | None:
        return self._repo.get_entity(source_id)

    def get_active_by_system_id(self, system_id: str) -> DataSource | None:
        for item in self.list_active():
            if item.system_id == system_id:
                return item
        return None

    def save(self, source: DataSource) -> None:
        self._repo.save_entity(source)


class PostgresTargetEnvironmentRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="target_environment",
            entity_type=TargetEnvironment,
            id_field="environment_id",
        )

    def list_active(self) -> list[TargetEnvironment]:
        return [item for item in self._repo.list_entities() if item.active]

    def get_by_id(self, environment_id: str) -> TargetEnvironment | None:
        return self._repo.get_entity(environment_id)

    def save(self, environment: TargetEnvironment) -> None:
        self._repo.save_entity(environment)


class PostgresDatasetProfileRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="dataset_profile",
            entity_type=DatasetProfile,
            id_field="profile_id",
        )

    def list_active(self) -> list[DatasetProfile]:
        return [item for item in self._repo.list_entities() if item.active]

    def get_by_id(self, profile_id: str) -> DatasetProfile | None:
        return self._repo.get_entity(profile_id)

    def save(self, profile: DatasetProfile) -> None:
        self._repo.save_entity(profile)


class PostgresBaselineRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(store=store, kind="baseline", entity_type=SanitizedBaseline, id_field="baseline_id")

    def list_active_for_system(self, system_id: str) -> list[SanitizedBaseline]:
        return [item for item in self._repo.list_entities() if item.system_id == system_id and item.active]

    def list_for_system(self, system_id: str) -> list[SanitizedBaseline]:
        return [item for item in self._repo.list_entities() if item.system_id == system_id]

    def get_by_id(self, baseline_id: str) -> SanitizedBaseline | None:
        return self._repo.get_entity(baseline_id)

    def add(self, baseline: SanitizedBaseline) -> None:
        self._repo.save_entity(baseline)

    def save(self, baseline: SanitizedBaseline) -> None:
        self._repo.save_entity(baseline)


class PostgresBaselineAssetRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="baseline_asset",
            entity_type=BaselineTableAsset,
            id_field="asset_id",
        )

    def list_for_baseline(self, baseline_id: str) -> list[BaselineTableAsset]:
        return [item for item in self._repo.list_entities() if item.baseline_id == baseline_id]

    def replace_for_baseline(self, baseline_id: str, assets: list[BaselineTableAsset]) -> None:
        for existing in self.list_for_baseline(baseline_id):
            self._repo.delete_entity(existing.asset_id)
        for asset in assets:
            self._repo.save_entity(asset)


class PostgresValidationRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="validation_report",
            entity_type=ValidationReport,
            id_field="report_id",
        )

    def get_latest_for_baseline(self, baseline_id: str) -> ValidationReport | None:
        reports = [item for item in self._repo.list_entities() if item.baseline_id == baseline_id]
        if not reports:
            return None
        return sorted(reports, key=lambda item: item.created_at, reverse=True)[0]

    def save(self, report: ValidationReport) -> None:
        self._repo.save_entity(report)


class PostgresMetadataCatalogRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._objects = JsonEntityRepository(
            store=store,
            kind="metadata_object",
            entity_type=MetadataObject,
            id_field="object_id",
        )
        self._relationships = JsonEntityRepository(
            store=store,
            kind="relationship",
            entity_type=Relationship,
            id_field="relationship_id",
        )

    def list_objects(
        self,
        source_id: str,
        *,
        object_type: MetadataObjectType | None = None,
    ) -> list[MetadataObject]:
        items = [item for item in self._objects.list_entities() if item.source_id == source_id]
        if object_type is not None:
            items = [item for item in items if item.object_type == object_type]
        return items

    def upsert_objects(self, objects: list[MetadataObject]) -> None:
        for item in objects:
            self._objects.save_entity(item)

    def upsert_relationships(self, relationships: list[Relationship]) -> None:
        for item in relationships:
            self._relationships.save_entity(item)

    def list_relationships(self, source_id: str) -> list[Relationship]:
        return [item for item in self._relationships.list_entities() if item.source_id == source_id]


class PostgresTransformationPolicyRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="transformation_policy",
            entity_type=TransformationPolicy,
            id_field="policy_id",
        )

    def list_active_for_system(self, system_id: str) -> list[TransformationPolicy]:
        return [item for item in self._repo.list_entities() if item.system_id == system_id and item.active]

    def save(self, policy: TransformationPolicy) -> None:
        self._repo.save_entity(policy)


class PostgresClassificationRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="sensitivity_tag",
            entity_type=SensitivityTag,
            id_field="tag_id",
        )

    def list_sensitivity_tags(self, source_id: str) -> list[SensitivityTag]:
        return [item for item in self._repo.list_entities() if item.source_id == source_id]

    def save(self, tag: SensitivityTag) -> None:
        self._repo.save_entity(tag)


class PostgresPublishJobRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(store=store, kind="publish_job", entity_type=PublishJob, id_field="job_id")

    def add(self, job: PublishJob) -> None:
        self._repo.save_entity(job)

    def get_by_id(self, job_id: str) -> PublishJob | None:
        return self._repo.get_entity(job_id)

    def list_all(self) -> list[PublishJob]:
        return self._repo.list_entities()

    def save(self, job: PublishJob) -> None:
        self._repo.save_entity(job)


class PostgresArtifactPublishJobRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="artifact_publish_job",
            entity_type=ArtifactPublishJob,
            id_field="job_id",
        )

    def add(self, job: ArtifactPublishJob) -> None:
        self._repo.save_entity(job)

    def get_by_id(self, job_id: str) -> ArtifactPublishJob | None:
        return self._repo.get_entity(job_id)

    def list_all(self) -> list[ArtifactPublishJob]:
        return self._repo.list_entities()

    def save(self, job: ArtifactPublishJob) -> None:
        self._repo.save_entity(job)


class PostgresBaselineRefreshJobRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="baseline_refresh_job",
            entity_type=BaselineRefreshJob,
            id_field="job_id",
        )

    def add(self, job: BaselineRefreshJob) -> None:
        self._repo.save_entity(job)

    def get_by_id(self, job_id: str) -> BaselineRefreshJob | None:
        return self._repo.get_entity(job_id)

    def list_all(self) -> list[BaselineRefreshJob]:
        return self._repo.list_entities()

    def save(self, job: BaselineRefreshJob) -> None:
        self._repo.save_entity(job)


class PostgresBaselineRefreshScheduleRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="baseline_refresh_schedule",
            entity_type=BaselineRefreshSchedule,
            id_field="schedule_id",
        )

    def add(self, schedule: BaselineRefreshSchedule) -> None:
        self._repo.save_entity(schedule)

    def get_by_id(self, schedule_id: str) -> BaselineRefreshSchedule | None:
        return self._repo.get_entity(schedule_id)

    def list_all(self) -> list[BaselineRefreshSchedule]:
        return self._repo.list_entities()

    def list_enabled(self) -> list[BaselineRefreshSchedule]:
        return [item for item in self._repo.list_entities() if item.enabled]

    def save(self, schedule: BaselineRefreshSchedule) -> None:
        self._repo.save_entity(schedule)


class PostgresExtractionJobRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="extraction_job",
            entity_type=ExtractionJob,
            id_field="job_id",
        )

    def add(self, job: ExtractionJob) -> None:
        self._repo.save_entity(job)

    def get_by_id(self, job_id: str) -> ExtractionJob | None:
        return self._repo.get_entity(job_id)

    def list_all(self) -> list[ExtractionJob]:
        return self._repo.list_entities()

    def save(self, job: ExtractionJob) -> None:
        self._repo.save_entity(job)


class PostgresExtractionPlanSnapshotRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="extraction_plan_snapshot",
            entity_type=ExtractionPlanSnapshot,
            id_field="snapshot_id",
        )

    def add(self, snapshot: ExtractionPlanSnapshot) -> None:
        self._repo.save_entity(snapshot)

    def get_by_id(self, snapshot_id: str) -> ExtractionPlanSnapshot | None:
        return self._repo.get_entity(snapshot_id)


class PostgresExtractionArtifactRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(
            store=store,
            kind="extraction_artifact",
            entity_type=ExtractionArtifact,
            id_field="artifact_id",
        )

    def add(self, artifact: ExtractionArtifact) -> None:
        self._repo.save_entity(artifact)

    def get_by_id(self, artifact_id: str) -> ExtractionArtifact | None:
        return self._repo.get_entity(artifact_id)

    def get_by_job_id(self, job_id: str) -> ExtractionArtifact | None:
        for item in self._repo.list_entities():
            if item.job_id == job_id:
                return item
        return None

    def list_all(self) -> list[ExtractionArtifact]:
        return self._repo.list_entities()

    def save(self, artifact: ExtractionArtifact) -> None:
        self._repo.save_entity(artifact)


class PostgresAuditEventRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(store=store, kind="audit_event", entity_type=AuditEvent, id_field="event_id")

    def add(self, event: AuditEvent) -> None:
        self._repo.save_entity(event)

    def list_for_subject(self, subject_id: str) -> list[AuditEvent]:
        return [item for item in self._repo.list_entities() if item.subject_id == subject_id]


class PostgresLineageRepository:
    def __init__(self, store: ControlPlaneJsonStore) -> None:
        self._repo = JsonEntityRepository(store=store, kind="lineage_record", entity_type=LineageRecord, id_field="record_id")

    def add(self, record: LineageRecord) -> None:
        self._repo.save_entity(record)

    def list_related(self, *, reference_type: str, reference_id: str) -> list[LineageRecord]:
        return [
            item
            for item in self._repo.list_entities()
            if (item.source_type == reference_type and item.source_id == reference_id)
            or (item.target_type == reference_type and item.target_id == reference_id)
        ]


__all__ = [
    "ControlPlaneJsonStore",
    "PsycopgBackend",
    "SqliteBackend",
    "PostgresSystemRepository",
    "PostgresDataSourceRepository",
    "PostgresTargetEnvironmentRepository",
    "PostgresDatasetProfileRepository",
    "PostgresBaselineRepository",
    "PostgresBaselineAssetRepository",
    "PostgresValidationRepository",
    "PostgresMetadataCatalogRepository",
    "PostgresTransformationPolicyRepository",
    "PostgresClassificationRepository",
    "PostgresPublishJobRepository",
    "PostgresArtifactPublishJobRepository",
    "PostgresBaselineRefreshJobRepository",
    "PostgresBaselineRefreshScheduleRepository",
    "PostgresExtractionJobRepository",
    "PostgresExtractionPlanSnapshotRepository",
    "PostgresExtractionArtifactRepository",
    "PostgresAuditEventRepository",
    "PostgresLineageRepository",
]
