import { z } from "zod";

export const summarySchema = z.record(z.string(), z.unknown());

export const systemSchema = z.object({
  system_id: z.string(),
  name: z.string(),
  source_engine: z.string(),
  available_profiles: z.number(),
});

export const sourceSchema = z.object({
  source_id: z.string(),
  system_id: z.string(),
  system_name: z.string(),
  engine_type: z.string(),
  database_name: z.string(),
  access_mode: z.string(),
});

export const environmentSchema = z.object({
  environment_id: z.string(),
  name: z.string(),
  environment_type: z.string(),
  engine_type: z.string(),
  target_endpoint: z.string(),
  active: z.boolean(),
});

export const datasetProfileSchema = z.object({
  profile_id: z.string(),
  system_id: z.string(),
  name: z.string(),
  system_name: z.string(),
  dataset_mode: z.string(),
  target_environment_type: z.string(),
  uses_sanitized_baseline: z.boolean(),
  preserve_constraints: z.boolean(),
  requires_approval: z.boolean(),
  active: z.boolean(),
});

export const engineCapabilitySchema = z.object({
  engine_type: z.string(),
  metadata_discovery_supported: z.boolean(),
  extraction_supported: z.boolean(),
  artifact_publish_supported: z.boolean(),
  baseline_refresh_supported: z.boolean(),
  baseline_publish_supported: z.boolean(),
  release_ready: z.boolean(),
});

export const engineCapabilityListingSchema = z.object({
  items: z.array(engineCapabilitySchema),
});

export const validationSummarySchema = z.object({
  status: z.string(),
  warning_count: z.number(),
  error_count: z.number(),
  validated_at: z.string().nullable(),
});

export const publishJobSchema = z.object({
  job_id: z.string(),
  status: z.string(),
  source_id: z.string(),
  sanitized_baseline_id: z.string().nullable(),
  baseline_validation_summary: validationSummarySchema.nullable(),
  target_environment_id: z.string(),
  dataset_profile_id: z.string(),
  requested_by: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  execution_summary: summarySchema,
});

export const auditEventSchema = z.object({
  event_id: z.string(),
  event_type: z.string(),
  actor: z.string(),
  subject_type: z.string(),
  subject_id: z.string(),
  details: summarySchema,
  created_at: z.string(),
});

export const lineageRecordSchema = z.object({
  record_id: z.string(),
  source_type: z.string(),
  source_id: z.string(),
  target_type: z.string(),
  target_id: z.string(),
  event_type: z.string(),
  created_at: z.string(),
  details: summarySchema,
});

export const lineageSchema = z.object({
  subject_type: z.string(),
  subject_id: z.string(),
  items: z.array(lineageRecordSchema),
});

export const extractionPlanPreviewSchema = z.object({
  source_id: z.string(),
  root_object_id: z.string(),
  include_related: z.boolean(),
  max_depth: z.number(),
  selected_columns: z.array(z.string()).nullable(),
  artifact_kind: z.string(),
  criteria: z.array(z.object({ field_name: z.string(), operator: z.string(), value: z.string() })),
  selected_objects: z.array(z.string()),
  selected_relationships: z.array(z.string()),
  notes: z.array(z.string()),
});

export const extractionJobSchema = z.object({
  job_id: z.string(),
  source_id: z.string(),
  system_id: z.string(),
  plan_snapshot_id: z.string(),
  root_object_id: z.string(),
  criteria: z.array(z.object({ field_name: z.string(), operator: z.string(), value: z.string() })),
  selected_columns: z.array(z.string()).nullable().optional(),
  include_related: z.boolean(),
  max_depth: z.number(),
  requested_by: z.string(),
  artifact_kind: z.string(),
  status: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  execution_summary: summarySchema,
});

export const artifactSchema = z.object({
  artifact_id: z.string(),
  job_id: z.string(),
  source_id: z.string(),
  root_object_id: z.string(),
  kind: z.string(),
  artifact_format: z.string(),
  artifact_path: z.string(),
  row_count: z.number(),
  file_size_bytes: z.number().nullable(),
  checksum: z.string().nullable(),
  column_count: z.number().nullable(),
  status: z.string(),
  available: z.boolean(),
  expires_at: z.string().nullable(),
  deleted_at: z.string().nullable(),
  created_at: z.string(),
});

export const artifactPublishJobSchema = z.object({
  job_id: z.string(),
  extraction_artifact_id: z.string(),
  source_id: z.string(),
  root_object_id: z.string(),
  target_environment_id: z.string(),
  requested_by: z.string(),
  status: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  execution_summary: summarySchema,
});

export const baselineEligibilitySchema = z.object({
  eligible: z.boolean(),
  reason: z.string(),
  details: z.record(z.string(), z.string()),
});

export const baselineValidationSummarySchema = validationSummarySchema;

export const baselineListItemSchema = z.object({
  baseline_id: z.string(),
  system_id: z.string(),
  system_name: z.string(),
  source_id: z.string(),
  dataset_profile_id: z.string(),
  target_environment_type: z.string(),
  engine_type: z.string(),
  version: z.string(),
  status: z.string(),
  refreshed_at: z.string(),
  asset_count: z.number(),
  storage_ready: z.boolean(),
  publish_eligible: z.boolean(),
  eligibility: baselineEligibilitySchema,
  validation_summary: baselineValidationSummarySchema.nullable(),
});

export const baselineListingSchema = z.object({
  filters: z.record(z.string(), z.string()),
  items: z.array(baselineListItemSchema),
});

export const baselineDetailSchema = z.object({
  baseline_id: z.string(),
  system_id: z.string(),
  system_name: z.string(),
  source_id: z.string(),
  dataset_profile_id: z.string(),
  target_environment_type: z.string(),
  engine_type: z.string(),
  version: z.string(),
  status: z.string(),
  created_at: z.string(),
  refreshed_at: z.string(),
  active: z.boolean(),
  asset_count: z.number(),
  storage_ready: z.boolean(),
  publish_eligible: z.boolean(),
  eligibility: baselineEligibilitySchema,
  validation_summary: baselineValidationSummarySchema.nullable(),
});

export const baselineAssetSchema = z.object({
  asset_id: z.string(),
  baseline_id: z.string(),
  source_id: z.string(),
  root_object_id: z.string(),
  artifact_format: z.string(),
  artifact_path: z.string(),
  row_count: z.number(),
  created_at: z.string(),
  checksum: z.string().nullable(),
  column_count: z.number().nullable(),
  import_order: z.number(),
});

export const baselineAssetListingSchema = z.object({
  baseline_id: z.string(),
  items: z.array(baselineAssetSchema),
});

export const baselineRefreshJobSchema = z.object({
  job_id: z.string(),
  system_id: z.string(),
  dataset_profile_id: z.string(),
  target_environment_type: z.string(),
  requested_by: z.string(),
  trigger_type: z.string(),
  refresh_schedule_id: z.string().nullable(),
  status: z.string(),
  baseline_id: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  result_summary: summarySchema,
});

export const refreshScheduleSchema = z.object({
  schedule_id: z.string(),
  system_id: z.string(),
  dataset_profile_id: z.string(),
  target_environment_type: z.string(),
  interval_minutes: z.number(),
  status: z.string(),
  created_by: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  next_run_at: z.string(),
  last_dispatched_at: z.string().nullable(),
});

export const metadataObjectSchema = z.object({
  object_id: z.string(),
  source_id: z.string(),
  system_id: z.string(),
  system_name: z.string(),
  object_type: z.string(),
  name: z.string(),
  qualified_name: z.string(),
  container_name: z.string().nullable().optional(),
  parent_object_id: z.string().nullable().optional(),
  logical_data_type: z.string().nullable().optional(),
  active: z.boolean(),
});

export const metadataCatalogSchema = z.object({
  system_id: z.string(),
  system_name: z.string(),
  source_id: z.string(),
  items: z.array(metadataObjectSchema),
});

export const relationshipSchema = z.object({
  relationship_id: z.string(),
  source_object_id: z.string(),
  target_object_id: z.string(),
  relationship_type: z.string(),
  inferred: z.boolean(),
  confidence: z.number().nullable(),
  active: z.boolean(),
});

export const relationshipListingSchema = z.object({
  system_id: z.string(),
  system_name: z.string(),
  source_id: z.string(),
  filters: z.record(z.string(), z.string()),
  items: z.array(relationshipSchema),
});

export const classificationSchema = z.object({
  tag_id: z.string(),
  object_id: z.string(),
  tag_name: z.string(),
  classification_status: z.string(),
  assigned_by: z.string(),
  approved: z.boolean(),
  active: z.boolean(),
});

export const classificationListingSchema = z.object({
  system_id: z.string(),
  system_name: z.string(),
  source_id: z.string(),
  filters: z.record(z.string(), z.string()),
  items: z.array(classificationSchema),
});

export const policySchema = z.object({
  policy_id: z.string(),
  system_id: z.string(),
  system_name: z.string(),
  object_name: z.string(),
  canonical_object_id: z.string().nullable(),
  legacy_object_name: z.string(),
  target_mode: z.string(),
  column_name: z.string(),
  sensitivity_tag: z.string(),
  transformation_type: z.string(),
  reversible: z.boolean(),
  active: z.boolean(),
});

export const policyListingSchema = z.object({
  filters: z.record(z.string(), z.string()),
  items: z.array(policySchema),
});

export const policyCoverageGapSchema = z.object({
  gap_type: z.string(),
  object_name: z.string(),
  severity: z.string(),
  message: z.string(),
  sensitivity_tags: z.array(z.string()),
});

export const policyCoverageReportSchema = z.object({
  system_id: z.string(),
  system_name: z.string(),
  source_id: z.string(),
  publish_ready: z.boolean(),
  evaluated_object_count: z.number(),
  covered_object_count: z.number(),
  blocking_gap_count: z.number(),
  informational_gap_count: z.number(),
  gaps: z.array(policyCoverageGapSchema),
});

export const governanceSummaryItemSchema = z.object({
  object_id: z.string(),
  object_type: z.string(),
  qualified_name: z.string(),
  classification_status: z.string(),
  sensitivity_tags: z.array(z.string()),
  policy_present: z.boolean(),
  policy_types: z.array(z.string()),
  coverage_state: z.string(),
  gap_types: z.array(z.string()),
});

export const governanceSummarySchema = z.object({
  system_id: z.string(),
  system_name: z.string(),
  source_id: z.string(),
  items: z.array(governanceSummaryItemSchema),
});
