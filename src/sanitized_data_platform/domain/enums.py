from enum import Enum


class DatabaseEngine(str, Enum):
    POSTGRES = "postgres"
    SQLSERVER = "sqlserver"
    ORACLE = "oracle"
    MYSQL = "mysql"
    MONGODB = "mongodb"


class EnvironmentType(str, Enum):
    DEV = "dev"
    TEST = "test"
    COLLAUDO = "collaudo"


class DatasetMode(str, Enum):
    FULL_CLONE = "full_clone"
    SUBSET = "subset"
    SCENARIO = "scenario"


class JobStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    EXTRACTING = "extracting"
    TRANSFORMING = "transforming"
    VALIDATING = "validating"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TransformationType(str, Enum):
    DETERMINISTIC_PSEUDONYMIZATION = "deterministic_pseudonymization"
    IRREVERSIBLE_MASKING = "irreversible_masking"
    REVERSIBLE_TOKENIZATION = "reversible_tokenization"
    HASHING = "hashing"
    SYNTHETIC_REPLACEMENT = "synthetic_replacement"
    GENERALIZATION = "generalization"
    REDACTION = "redaction"


class MetadataObjectType(str, Enum):
    SCHEMA = "schema"
    TABLE = "table"
    COLUMN = "column"
    RELATIONSHIP = "relationship"
    INDEX = "index"
    VIEW = "view"
    SEQUENCE = "sequence"


class PolicyCoverageSeverity(str, Enum):
    BLOCKING = "blocking"
    INFORMATIONAL = "informational"
