import { z } from "zod";
import {
  artifactPublishJobSchema,
  artifactSchema,
  auditEventSchema,
  baselineAssetListingSchema,
  baselineDetailSchema,
  baselineListingSchema,
  baselineRefreshJobSchema,
  classificationListingSchema,
  datasetProfileSchema,
  engineCapabilityListingSchema,
  engineCapabilitySchema,
  environmentSchema,
  extractionJobSchema,
  extractionPlanPreviewSchema,
  governanceSummarySchema,
  lineageSchema,
  metadataCatalogSchema,
  policyCoverageReportSchema,
  policyListingSchema,
  publishJobSchema,
  refreshScheduleSchema,
  relationshipListingSchema,
  sourceSchema,
  systemSchema,
} from "./schemas";

const emptyObject = z.object({});

export type PublishJob = z.infer<typeof publishJobSchema>;
export type ExtractionJob = z.infer<typeof extractionJobSchema>;
export type ExtractionArtifact = z.infer<typeof artifactSchema>;
export type ArtifactPublishJob = z.infer<typeof artifactPublishJobSchema>;
export type BaselineDetail = z.infer<typeof baselineDetailSchema>;

async function parseJson<T>(response: Response, schema: z.ZodSchema<T>): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const errorSchema = z.object({ error: z.string() }).catch({ error: "Unexpected error" });
    const parsed = errorSchema.parse(payload);
    throw new Error(parsed.error);
  }
  return schema.parse(payload);
}

export class ApiClient {
  constructor(private readonly baseUrl = "/") {}

  private async get<T>(path: string, schema: z.ZodSchema<T>): Promise<T> {
    const response = await fetch(new URL(path, this.baseUrl), {
      headers: { Accept: "application/json" },
    });
    return parseJson(response, schema);
  }

  private async post<T>(
    path: string,
    body: unknown,
    schema: z.ZodSchema<T>,
  ): Promise<T> {
    const response = await fetch(new URL(path, this.baseUrl), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
    });
    return parseJson(response, schema);
  }

  listSystems() {
    return this.get("/api/v1/systems", z.array(systemSchema));
  }

  listSources() {
    return this.get("/api/v1/sources", z.array(sourceSchema));
  }

  listEnvironments() {
    return this.get("/api/v1/environments", z.array(environmentSchema));
  }

  listDatasetProfiles(params?: { sourceId?: string; targetEnvironmentId?: string }) {
    const search = new URLSearchParams();
    if (params?.sourceId) search.set("sourceId", params.sourceId);
    if (params?.targetEnvironmentId) search.set("targetEnvironmentId", params.targetEnvironmentId);
    const suffix = search.size > 0 ? `?${search.toString()}` : "";
    return this.get(`/api/v1/dataset-profiles${suffix}`, z.array(datasetProfileSchema));
  }

  listEngineCapabilities() {
    return this.get("/api/v1/engine-capabilities", engineCapabilityListingSchema);
  }

  getEngineCapability(engineType: string) {
    return this.get(`/api/v1/engine-capabilities/${engineType}`, engineCapabilitySchema);
  }

  createPublishJob(body: {
    sourceId: string;
    targetEnvironmentId: string;
    datasetProfileId: string;
    requestedBy: string;
  }) {
    return this.post("/api/v1/jobs", body, publishJobSchema);
  }

  listPublishJobs() {
    return this.get("/api/v1/jobs", z.array(publishJobSchema));
  }

  getPublishJob(jobId: string) {
    return this.get(`/api/v1/jobs/${jobId}`, publishJobSchema);
  }

  listPublishAudit(jobId: string) {
    return this.get(`/api/v1/jobs/${jobId}/audit-events`, z.array(auditEventSchema));
  }

  getPublishLineage(jobId: string) {
    return this.get(`/api/v1/jobs/${jobId}/lineage`, lineageSchema);
  }

  previewExtractionPlan(body: {
    sourceId: string;
    rootObjectId: string;
    criteria: Array<{ fieldName: string; operator: string; value: string }>;
    includeRelated: boolean;
    maxDepth: number;
    selectedColumns?: string[];
    artifactKind?: string;
  }) {
    return this.post("/api/v1/extraction-plans/preview", body, extractionPlanPreviewSchema);
  }

  createExtractionJob(body: {
    sourceId: string;
    rootObjectId: string;
    criteria: Array<{ fieldName: string; operator: string; value: string }>;
    includeRelated: boolean;
    maxDepth: number;
    requestedBy: string;
    selectedColumns?: string[];
    artifactKind?: string;
  }) {
    return this.post("/api/v1/extraction-jobs", body, extractionJobSchema);
  }

  listExtractionJobs() {
    return this.get("/api/v1/extraction-jobs", z.array(extractionJobSchema));
  }

  getExtractionJob(jobId: string) {
    return this.get(`/api/v1/extraction-jobs/${jobId}`, extractionJobSchema);
  }

  getExtractionJobArtifact(jobId: string) {
    return this.get(`/api/v1/extraction-jobs/${jobId}/artifact`, artifactSchema);
  }

  listExtractionAudit(jobId: string) {
    return this.get(`/api/v1/extraction-jobs/${jobId}/audit-events`, z.array(auditEventSchema));
  }

  getExtractionLineage(jobId: string) {
    return this.get(`/api/v1/extraction-jobs/${jobId}/lineage`, lineageSchema);
  }

  getArtifact(artifactId: string) {
    return this.get(`/api/v1/extraction-artifacts/${artifactId}`, artifactSchema);
  }

  getArtifactLineage(artifactId: string) {
    return this.get(`/api/v1/extraction-artifacts/${artifactId}/lineage`, lineageSchema);
  }

  listArtifactAudit(artifactId: string) {
    return this.get(`/api/v1/extraction-artifacts/${artifactId}/audit-events`, z.array(auditEventSchema));
  }

  createArtifactPublishJob(body: {
    extractionArtifactId: string;
    targetEnvironmentId: string;
    requestedBy: string;
  }) {
    return this.post("/api/v1/artifact-publish-jobs", body, artifactPublishJobSchema);
  }

  listArtifactPublishJobs() {
    return this.get("/api/v1/artifact-publish-jobs", z.array(artifactPublishJobSchema));
  }

  getArtifactPublishJob(jobId: string) {
    return this.get(`/api/v1/artifact-publish-jobs/${jobId}`, artifactPublishJobSchema);
  }

  getArtifactPublishLineage(jobId: string) {
    return this.get(`/api/v1/artifact-publish-jobs/${jobId}/lineage`, lineageSchema);
  }

  listArtifactPublishAudit(jobId: string) {
    return this.get(`/api/v1/artifact-publish-jobs/${jobId}/audit-events`, z.array(auditEventSchema));
  }

  listBaselines(params?: {
    systemId?: string;
    targetEnvironmentType?: string;
    datasetProfileId?: string;
  }) {
    const search = new URLSearchParams();
    if (params?.systemId) search.set("systemId", params.systemId);
    if (params?.targetEnvironmentType) search.set("targetEnvironmentType", params.targetEnvironmentType);
    if (params?.datasetProfileId) search.set("datasetProfileId", params.datasetProfileId);
    const suffix = search.size > 0 ? `?${search.toString()}` : "";
    return this.get(`/api/v1/baselines${suffix}`, baselineListingSchema);
  }

  getBaseline(baselineId: string) {
    return this.get(`/api/v1/baselines/${baselineId}`, baselineDetailSchema);
  }

  listBaselineAssets(baselineId: string) {
    return this.get(`/api/v1/baselines/${baselineId}/assets`, baselineAssetListingSchema);
  }

  getBaselineLineage(baselineId: string) {
    return this.get(`/api/v1/baselines/${baselineId}/lineage`, lineageSchema);
  }

  getBaselineValidation(baselineId: string) {
    return this.get(`/api/v1/baselines/${baselineId}/validation`, z.any());
  }

  listBaselineRefreshJobs() {
    return this.get("/api/v1/baseline-refresh-jobs", z.array(baselineRefreshJobSchema));
  }

  getBaselineRefreshJob(jobId: string) {
    return this.get(`/api/v1/baseline-refresh-jobs/${jobId}`, baselineRefreshJobSchema);
  }

  listBaselineRefreshAudit(jobId: string) {
    return this.get(`/api/v1/baseline-refresh-jobs/${jobId}/audit-events`, z.array(auditEventSchema));
  }

  listRefreshSchedules() {
    return this.get("/api/v1/refresh-schedules", z.array(refreshScheduleSchema));
  }

  createRefreshSchedule(body: {
    systemId: string;
    datasetProfileId: string;
    targetEnvironmentType: string;
    intervalMinutes: number;
    createdBy: string;
  }) {
    return this.post("/api/v1/refresh-schedules", body, refreshScheduleSchema);
  }

  listMetadataObjects(systemId: string) {
    return this.get(`/api/v1/metadata/systems/${systemId}`, metadataCatalogSchema);
  }

  listRelationships(systemId: string, params?: { objectId?: string; relationshipType?: string }) {
    const search = new URLSearchParams();
    if (params?.objectId) search.set("objectId", params.objectId);
    if (params?.relationshipType) search.set("relationshipType", params.relationshipType);
    const suffix = search.size > 0 ? `?${search.toString()}` : "";
    return this.get(`/api/v1/metadata/systems/${systemId}/relationships${suffix}`, relationshipListingSchema);
  }

  listClassifications(systemId: string, params?: { objectId?: string; classificationStatus?: string; sensitivityTag?: string }) {
    const search = new URLSearchParams();
    if (params?.objectId) search.set("objectId", params.objectId);
    if (params?.classificationStatus) search.set("classificationStatus", params.classificationStatus);
    if (params?.sensitivityTag) search.set("sensitivityTag", params.sensitivityTag);
    const suffix = search.size > 0 ? `?${search.toString()}` : "";
    return this.get(`/api/v1/metadata/systems/${systemId}/classifications${suffix}`, classificationListingSchema);
  }

  listPolicies(params?: { systemId?: string; objectName?: string; columnName?: string; targetMode?: string }) {
    const search = new URLSearchParams();
    if (params?.systemId) search.set("systemId", params.systemId);
    if (params?.objectName) search.set("objectName", params.objectName);
    if (params?.columnName) search.set("columnName", params.columnName);
    if (params?.targetMode) search.set("targetMode", params.targetMode);
    const suffix = search.size > 0 ? `?${search.toString()}` : "";
    return this.get(`/api/v1/policies${suffix}`, policyListingSchema);
  }

  getPolicyCoverage(systemId: string) {
    return this.get(`/api/v1/policy-coverage/${systemId}`, policyCoverageReportSchema);
  }

  getGovernanceSummary(systemId: string) {
    return this.get(`/api/v1/metadata/systems/${systemId}/governance-summary`, governanceSummarySchema);
  }

  listRecentNothing() {
    return Promise.resolve(emptyObject.parse({}));
  }
}

const configuredApiBaseUrl =
  typeof import.meta !== "undefined" &&
  import.meta.env &&
  typeof import.meta.env.VITE_API_BASE_URL === "string" &&
  import.meta.env.VITE_API_BASE_URL.length > 0
    ? import.meta.env.VITE_API_BASE_URL
    : undefined;

export const apiClient = new ApiClient(
  configuredApiBaseUrl ??
    (typeof window === "undefined" ? "http://localhost:8000" : window.location.origin),
);
