import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMemo, useState } from "react";
import { apiClient } from "./lib/api";
import { formatDateTime, titleCase } from "./lib/format";
import { DataTable } from "./components/DataTable";
import { ExplainPanel } from "./components/ExplainPanel";
import { KeyValueList } from "./components/KeyValueList";
import { PageHeader } from "./components/PageHeader";
import { SectionCard } from "./components/SectionCard";
import { StatusChip, toneForStatus } from "./components/StatusChip";

function useSystems() {
  return useQuery({ queryKey: ["systems"], queryFn: () => apiClient.listSystems() });
}

function useSources() {
  return useQuery({ queryKey: ["sources"], queryFn: () => apiClient.listSources() });
}

function useEnvironments() {
  return useQuery({ queryKey: ["environments"], queryFn: () => apiClient.listEnvironments() });
}

function QueryState<T>({
  query,
  children,
}: {
  query: { isPending: boolean; error: Error | null; data: T | undefined };
  children: (data: T) => JSX.Element;
}) {
  if (query.isPending) return <div className="loading-state">Loading…</div>;
  if (query.error) return <div className="error-state">{query.error.message}</div>;
  return children(query.data as T);
}

function SummaryGrid({ children }: { children: React.ReactNode }) {
  return <div className="summary-grid">{children}</div>;
}

function SummaryMetric({ label, value, tone = "default" }: { label: string; value: string | number; tone?: "default" | "accent" }) {
  return (
    <div className={`summary-metric summary-metric--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function HomePage() {
  const systems = useSystems();
  const capabilities = useQuery({ queryKey: ["engine-capabilities"], queryFn: () => apiClient.listEngineCapabilities() });
  const publishJobs = useQuery({ queryKey: ["publish-jobs"], queryFn: () => apiClient.listPublishJobs() });
  const baselines = useQuery({ queryKey: ["baselines"], queryFn: () => apiClient.listBaselines() });

  return (
    <div className="page-stack">
      <PageHeader title="Overview" description="One cockpit for self-service delivery, governance visibility, and operational traceability." />
      <QueryState query={systems}>
        {(systemsData) => (
          <SummaryGrid>
            <SummaryMetric label="Systems" value={systemsData.length} tone="accent" />
            <SummaryMetric label="Release-ready engines" value={capabilities.data?.items.filter((item) => item.release_ready).length ?? 0} />
            <SummaryMetric label="Active baselines" value={baselines.data?.items.length ?? 0} />
            <SummaryMetric label="Publish jobs" value={publishJobs.data?.length ?? 0} />
          </SummaryGrid>
        )}
      </QueryState>
      <div className="two-column">
        <SectionCard title="Engine capabilities" subtitle="Runtime readiness per supported database engine.">
          <QueryState query={capabilities}>
            {(data) => (
              <DataTable
                rows={data.items}
                columns={[
                  { key: "engine", header: "Engine", render: (item) => item.engine_type },
                  { key: "release", header: "Release ready", render: (item) => <StatusChip tone={item.release_ready ? "success" : "warning"}>{item.release_ready ? "yes" : "partial"}</StatusChip> },
                  { key: "extract", header: "Extraction", render: (item) => <StatusChip tone={item.extraction_supported ? "success" : "danger"}>{item.extraction_supported ? "supported" : "missing"}</StatusChip> },
                ]}
              />
            )}
          </QueryState>
        </SectionCard>
        <SectionCard title="Recent publish jobs" subtitle="The newest standard publish requests.">
          <QueryState query={publishJobs}>
            {(jobs) => (
              <DataTable
                rows={jobs.slice(0, 5)}
                columns={[
                  { key: "job", header: "Job", render: (job) => <Link to={`/publish/jobs/${job.job_id}`}>{job.job_id}</Link> },
                  { key: "status", header: "Status", render: (job) => <StatusChip tone={toneForStatus(job.status)}>{job.status}</StatusChip> },
                  { key: "baseline", header: "Baseline", render: (job) => job.sanitized_baseline_id ?? "n/a" },
                ]}
                emptyTitle="No publish jobs yet"
                emptyDescription="Start with a simple self-service publish request."
              />
            )}
          </QueryState>
        </SectionCard>
      </div>
    </div>
  );
}

export function PublishRequestPage() {
  const navigate = useNavigate();
  const systems = useSystems();
  const sources = useSources();
  const environments = useEnvironments();
  const [form, setForm] = useState({
    systemId: "",
    sourceId: "",
    targetEnvironmentId: "",
    datasetProfileId: "",
    requestedBy: "developer@example.internal",
  });
  const profiles = useQuery({
    queryKey: ["dataset-profiles", form.sourceId, form.targetEnvironmentId],
    queryFn: () => apiClient.listDatasetProfiles({ sourceId: form.sourceId, targetEnvironmentId: form.targetEnvironmentId }),
    enabled: Boolean(form.sourceId && form.targetEnvironmentId),
  });
  const createJob = useMutation({
    mutationFn: () =>
      apiClient.createPublishJob({
        sourceId: form.sourceId,
        targetEnvironmentId: form.targetEnvironmentId,
        datasetProfileId: form.datasetProfileId,
        requestedBy: form.requestedBy,
      }),
    onSuccess: (job) => navigate(`/publish/jobs/${job.job_id}`),
  });

  const availableSources = useMemo(
    () => (sources.data ?? []).filter((item) => !form.systemId || item.system_id === form.systemId),
    [sources.data, form.systemId],
  );

  return (
    <div className="page-stack">
      <PageHeader title="Request publish" description="Simple mode: choose the system, target environment, and approved dataset profile, then launch." />
      <SectionCard title="Publish request" subtitle="Guardrailed self-service flow for developer/tester usage.">
        <div className="form-grid">
          <label>
            System
            <select value={form.systemId} onChange={(event) => setForm((current) => ({ ...current, systemId: event.target.value, sourceId: "", datasetProfileId: "" }))}>
              <option value="">Select system</option>
              {(systems.data ?? []).map((system) => (
                <option key={system.system_id} value={system.system_id}>
                  {system.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Source
            <select value={form.sourceId} onChange={(event) => setForm((current) => ({ ...current, sourceId: event.target.value, datasetProfileId: "" }))}>
              <option value="">Select source</option>
              {availableSources.map((source) => (
                <option key={source.source_id} value={source.source_id}>
                  {source.system_name} / {source.database_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Target environment
            <select value={form.targetEnvironmentId} onChange={(event) => setForm((current) => ({ ...current, targetEnvironmentId: event.target.value, datasetProfileId: "" }))}>
              <option value="">Select target</option>
              {(environments.data ?? []).map((environment) => (
                <option key={environment.environment_id} value={environment.environment_id}>
                  {environment.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Dataset profile
            <select value={form.datasetProfileId} onChange={(event) => setForm((current) => ({ ...current, datasetProfileId: event.target.value }))}>
              <option value="">Select profile</option>
              {(profiles.data ?? []).map((profile) => (
                <option key={profile.profile_id} value={profile.profile_id}>
                  {profile.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Requested by
            <input value={form.requestedBy} onChange={(event) => setForm((current) => ({ ...current, requestedBy: event.target.value }))} />
          </label>
        </div>
        {createJob.isError ? <div className="error-state">{createJob.error.message}</div> : null}
        <div className="form-actions">
          <button
            className="primary-button"
            onClick={() => createJob.mutate()}
            disabled={!form.sourceId || !form.targetEnvironmentId || !form.datasetProfileId || createJob.isPending}
          >
            {createJob.isPending ? "Submitting…" : "Create publish job"}
          </button>
        </div>
      </SectionCard>
    </div>
  );
}

export function PublishJobsPage() {
  const jobs = useQuery({ queryKey: ["publish-jobs"], queryFn: () => apiClient.listPublishJobs(), refetchInterval: 10000 });
  return (
    <div className="page-stack">
      <PageHeader title="Publish jobs" description="Track standard publish requests, outcomes, and baseline context." actions={<Link className="secondary-button" to="/publish/new">New publish request</Link>} />
      <SectionCard title="Jobs" subtitle="Polling is enabled for active operational visibility.">
        <QueryState query={jobs}>
          {(data) => (
            <DataTable
              rows={data}
              columns={[
                { key: "job", header: "Job", render: (job) => <Link to={`/publish/jobs/${job.job_id}`}>{job.job_id}</Link> },
                { key: "status", header: "Status", render: (job) => <StatusChip tone={toneForStatus(job.status)}>{job.status}</StatusChip> },
                { key: "profile", header: "Profile", render: (job) => job.dataset_profile_id },
                { key: "created", header: "Created", render: (job) => formatDateTime(job.created_at) },
              ]}
            />
          )}
        </QueryState>
      </SectionCard>
    </div>
  );
}

export function PublishJobDetailPage() {
  const { jobId = "" } = useParams();
  const job = useQuery({ queryKey: ["publish-job", jobId], queryFn: () => apiClient.getPublishJob(jobId) });
  const audit = useQuery({ queryKey: ["publish-audit", jobId], queryFn: () => apiClient.listPublishAudit(jobId) });
  const lineage = useQuery({ queryKey: ["publish-lineage", jobId], queryFn: () => apiClient.getPublishLineage(jobId) });
  return (
    <DetailLayout
      title={`Publish job ${jobId}`}
      description="Validation, audit trail, and lineage for a standard publish flow."
      summaryQuery={job}
      summary={(data) => (
        <KeyValueList
          items={[
            { label: "Status", value: data.status },
            { label: "Source", value: data.source_id },
            { label: "Baseline", value: data.sanitized_baseline_id ?? "n/a" },
            { label: "Target", value: data.target_environment_id },
            { label: "Requested by", value: data.requested_by },
          ]}
        />
      )}
      sidePanels={[
        <ExplainPanel key="validation" title="Validation summary">
          {job.data?.baseline_validation_summary ? (
            <KeyValueList
              items={[
                { label: "Status", value: job.data.baseline_validation_summary.status },
                { label: "Warnings", value: String(job.data.baseline_validation_summary.warning_count) },
                { label: "Errors", value: String(job.data.baseline_validation_summary.error_count) },
              ]}
            />
          ) : (
            <p>No validation summary was attached to this publish request.</p>
          )}
        </ExplainPanel>,
        <TimelinePanel key="audit" title="Audit events" query={audit} />,
        <LineagePanel key="lineage" query={lineage} />,
      ]}
    />
  );
}

export function ExtractionPreviewPage() {
  const navigate = useNavigate();
  const systems = useSystems();
  const sources = useSources();
  const [systemId, setSystemId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [rootObjectId, setRootObjectId] = useState("");
  const [artifactKind, setArtifactKind] = useState("sample");
  const [selectedColumns, setSelectedColumns] = useState("");
  const [criterion, setCriterion] = useState({ fieldName: "customer_id", operator: "eq", value: "42" });
  const metadata = useQuery({
    queryKey: ["metadata", systemId],
    queryFn: () => apiClient.listMetadataObjects(systemId),
    enabled: Boolean(systemId),
  });
  const preview = useMutation({
    mutationFn: () =>
      apiClient.previewExtractionPlan({
        sourceId,
        rootObjectId,
        includeRelated: false,
        maxDepth: 1,
        artifactKind,
        selectedColumns: selectedColumns ? selectedColumns.split(",").map((item) => item.trim()).filter(Boolean) : undefined,
        criteria: criterion.fieldName ? [criterion] : [],
      }),
  });
  const createJob = useMutation({
    mutationFn: () =>
      apiClient.createExtractionJob({
        sourceId,
        rootObjectId,
        includeRelated: false,
        maxDepth: 1,
        artifactKind,
        requestedBy: "developer@example.internal",
        selectedColumns: selectedColumns ? selectedColumns.split(",").map((item) => item.trim()).filter(Boolean) : undefined,
        criteria: criterion.fieldName ? [criterion] : [],
      }),
    onSuccess: (job) => navigate(`/extraction/jobs/${job.job_id}`),
  });

  const tableOptions = (metadata.data?.items ?? []).filter((item) => item.object_type === "table");
  const availableSources = (sources.data ?? []).filter((item) => item.system_id === systemId);

  return (
    <div className="page-stack">
      <PageHeader title="Plan and run extraction" description="Preview the root-table plan, then submit an extraction job backed by a persisted snapshot." />
      <SectionCard title="Extraction builder" subtitle="Current scope: root-table extraction with criteria, projection narrowing, and sample/full artifact modes.">
        <div className="form-grid">
          <label>
            System
            <select value={systemId} onChange={(event) => { setSystemId(event.target.value); setSourceId(""); setRootObjectId(""); }}>
              <option value="">Select system</option>
              {(systems.data ?? []).map((system) => (
                <option key={system.system_id} value={system.system_id}>{system.name}</option>
              ))}
            </select>
          </label>
          <label>
            Source
            <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
              <option value="">Select source</option>
              {availableSources.map((source) => (
                <option key={source.source_id} value={source.source_id}>{source.database_name}</option>
              ))}
            </select>
          </label>
          <label>
            Root object
            <select value={rootObjectId} onChange={(event) => setRootObjectId(event.target.value)}>
              <option value="">Select table</option>
              {tableOptions.map((item) => (
                <option key={item.object_id} value={item.object_id}>{item.qualified_name}</option>
              ))}
            </select>
          </label>
          <label>
            Artifact kind
            <select value={artifactKind} onChange={(event) => setArtifactKind(event.target.value)}>
              <option value="sample">sample</option>
              <option value="full">full</option>
            </select>
          </label>
          <label>
            Selected columns
            <input value={selectedColumns} onChange={(event) => setSelectedColumns(event.target.value)} placeholder="customer_id,email" />
          </label>
          <label>
            Criterion field
            <input value={criterion.fieldName} onChange={(event) => setCriterion((current) => ({ ...current, fieldName: event.target.value }))} />
          </label>
          <label>
            Operator
            <select value={criterion.operator} onChange={(event) => setCriterion((current) => ({ ...current, operator: event.target.value }))}>
              {["eq", "ne", "gt", "gte", "lt", "lte", "like", "ilike"].map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Value
            <input value={criterion.value} onChange={(event) => setCriterion((current) => ({ ...current, value: event.target.value }))} />
          </label>
        </div>
        <div className="form-actions">
          <button className="secondary-button" onClick={() => preview.mutate()} disabled={!sourceId || !rootObjectId}>Preview plan</button>
          <button className="primary-button" onClick={() => createJob.mutate()} disabled={!sourceId || !rootObjectId}>Create extraction job</button>
        </div>
        {preview.isError ? <div className="error-state">{preview.error.message}</div> : null}
        {createJob.isError ? <div className="error-state">{createJob.error.message}</div> : null}
      </SectionCard>
      {preview.data ? (
        <div className="two-column">
          <SectionCard title="Plan preview" subtitle="Bounded explanation of selected objects and relationships.">
            <KeyValueList
              items={[
                { label: "Root object", value: preview.data.root_object_id },
                { label: "Artifact kind", value: preview.data.artifact_kind },
                { label: "Selected objects", value: String(preview.data.selected_objects.length) },
                { label: "Selected relationships", value: String(preview.data.selected_relationships.length) },
              ]}
            />
          </SectionCard>
          <ExplainPanel title="Planning notes">
            <ul className="bullet-list">
              {preview.data.notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
          </ExplainPanel>
        </div>
      ) : null}
    </div>
  );
}

export function ExtractionJobsPage() {
  const jobs = useQuery({ queryKey: ["extraction-jobs"], queryFn: () => apiClient.listExtractionJobs(), refetchInterval: 10000 });
  return (
    <EntityListPage
      title="Extraction jobs"
      description="Monitor extraction execution, artifacts, and transformation-backed materialization."
      query={jobs}
      rows={(data) => data}
      columns={[
        { key: "job", header: "Job", render: (job) => <Link to={`/extraction/jobs/${job.job_id}`}>{job.job_id}</Link> },
        { key: "status", header: "Status", render: (job) => <StatusChip tone={toneForStatus(job.status)}>{job.status}</StatusChip> },
        { key: "kind", header: "Artifact kind", render: (job) => job.artifact_kind },
        { key: "root", header: "Root object", render: (job) => job.root_object_id },
      ]}
    />
  );
}

export function ExtractionJobDetailPage() {
  const { jobId = "" } = useParams();
  const job = useQuery({ queryKey: ["extraction-job", jobId], queryFn: () => apiClient.getExtractionJob(jobId) });
  const audit = useQuery({ queryKey: ["extraction-audit", jobId], queryFn: () => apiClient.listExtractionAudit(jobId) });
  const lineage = useQuery({ queryKey: ["extraction-lineage", jobId], queryFn: () => apiClient.getExtractionLineage(jobId) });
  const artifact = useQuery({ queryKey: ["extraction-artifact-for-job", jobId], queryFn: () => apiClient.getExtractionJobArtifact(jobId) });
  return (
    <DetailLayout
      title={`Extraction job ${jobId}`}
      description="Inspect execution, lineage, and the resulting artifact."
      summaryQuery={job}
      summary={(data) => (
        <KeyValueList items={[
          { label: "Status", value: data.status },
          { label: "Root object", value: data.root_object_id },
          { label: "Artifact kind", value: data.artifact_kind },
          { label: "Requested by", value: data.requested_by },
        ]} />
      )}
      sidePanels={[
        <ExplainPanel key="artifact" title="Artifact handoff">
          {artifact.data ? <p><Link to={`/artifacts/${artifact.data.artifact_id}`}>Open artifact {artifact.data.artifact_id}</Link></p> : <p>No artifact is visible yet.</p>}
        </ExplainPanel>,
        <TimelinePanel key="audit" title="Audit events" query={audit} />,
        <LineagePanel key="lineage" query={lineage} />,
      ]}
    />
  );
}

export function ArtifactDetailPage() {
  const { artifactId = "" } = useParams();
  const environments = useEnvironments();
  const artifact = useQuery({ queryKey: ["artifact", artifactId], queryFn: () => apiClient.getArtifact(artifactId) });
  const audit = useQuery({ queryKey: ["artifact-audit", artifactId], queryFn: () => apiClient.listArtifactAudit(artifactId) });
  const lineage = useQuery({ queryKey: ["artifact-lineage", artifactId], queryFn: () => apiClient.getArtifactLineage(artifactId) });
  const [targetEnvironmentId, setTargetEnvironmentId] = useState("");
  const publishArtifact = useMutation({
    mutationFn: () =>
      apiClient.createArtifactPublishJob({
        extractionArtifactId: artifactId,
        targetEnvironmentId,
        requestedBy: "developer@example.internal",
      }),
  });

  return (
    <DetailLayout
      title={`Artifact ${artifactId}`}
      description="Lifecycle state, operational metadata, lineage, and artifact-based delivery."
      summaryQuery={artifact}
      summary={(data) => (
        <KeyValueList items={[
          { label: "Status", value: data.status },
          { label: "Format", value: data.artifact_format },
          { label: "Kind", value: data.kind },
          { label: "Rows", value: String(data.row_count) },
          { label: "Checksum", value: data.checksum ?? "n/a" },
        ]} />
      )}
      sidePanels={[
        <ExplainPanel key="publish" title="Artifact-based delivery">
          <label className="stack-field">
            Target environment
            <select value={targetEnvironmentId} onChange={(event) => setTargetEnvironmentId(event.target.value)}>
              <option value="">Select target</option>
              {(environments.data ?? []).map((environment) => (
                <option key={environment.environment_id} value={environment.environment_id}>{environment.name}</option>
              ))}
            </select>
          </label>
          <button className="primary-button" disabled={!targetEnvironmentId} onClick={() => publishArtifact.mutate()}>
            Create artifact publish job
          </button>
          {publishArtifact.data ? <p><Link to={`/artifact-publish/jobs/${publishArtifact.data.job_id}`}>Open job {publishArtifact.data.job_id}</Link></p> : null}
          {publishArtifact.isError ? <div className="error-state">{publishArtifact.error.message}</div> : null}
        </ExplainPanel>,
        <TimelinePanel key="audit" title="Audit events" query={audit} />,
        <LineagePanel key="lineage" query={lineage} />,
      ]}
    />
  );
}

export function ArtifactPublishJobsPage() {
  const jobs = useQuery({ queryKey: ["artifact-publish-jobs"], queryFn: () => apiClient.listArtifactPublishJobs(), refetchInterval: 10000 });
  return (
    <EntityListPage
      title="Artifact publish jobs"
      description="Operational bridge from extraction artifacts into non-production delivery."
      query={jobs}
      rows={(data) => data}
      columns={[
        { key: "job", header: "Job", render: (job) => <Link to={`/artifact-publish/jobs/${job.job_id}`}>{job.job_id}</Link> },
        { key: "status", header: "Status", render: (job) => <StatusChip tone={toneForStatus(job.status)}>{job.status}</StatusChip> },
        { key: "artifact", header: "Artifact", render: (job) => <Link to={`/artifacts/${job.extraction_artifact_id}`}>{job.extraction_artifact_id}</Link> },
        { key: "target", header: "Target", render: (job) => job.target_environment_id },
      ]}
    />
  );
}

export function ArtifactPublishJobDetailPage() {
  const { jobId = "" } = useParams();
  const job = useQuery({ queryKey: ["artifact-publish-job", jobId], queryFn: () => apiClient.getArtifactPublishJob(jobId) });
  const audit = useQuery({ queryKey: ["artifact-publish-audit", jobId], queryFn: () => apiClient.listArtifactPublishAudit(jobId) });
  const lineage = useQuery({ queryKey: ["artifact-publish-lineage", jobId], queryFn: () => apiClient.getArtifactPublishLineage(jobId) });
  return (
    <DetailLayout
      title={`Artifact publish job ${jobId}`}
      description="Delivery result, source artifact, and target-environment traceability."
      summaryQuery={job}
      summary={(data) => (
        <KeyValueList items={[
          { label: "Status", value: data.status },
          { label: "Artifact", value: data.extraction_artifact_id },
          { label: "Target", value: data.target_environment_id },
          { label: "Root object", value: data.root_object_id },
        ]} />
      )}
      sidePanels={[
        <TimelinePanel key="audit" title="Audit events" query={audit} />,
        <LineagePanel key="lineage" query={lineage} />,
      ]}
    />
  );
}

export function BaselinesPage() {
  const baselines = useQuery({ queryKey: ["baselines"], queryFn: () => apiClient.listBaselines() });
  return (
    <EntityListPage
      title="Baselines"
      description="Active sanitized baselines, eligibility, validation, and storage readiness."
      query={baselines}
      rows={(data) => data.items}
      columns={[
        { key: "baseline", header: "Baseline", render: (item) => <Link to={`/baselines/${item.baseline_id}`}>{item.baseline_id}</Link> },
        { key: "status", header: "Status", render: (item) => <StatusChip tone={toneForStatus(item.status)}>{item.status}</StatusChip> },
        { key: "eligible", header: "Eligibility", render: (item) => <StatusChip tone={item.publish_eligible ? "success" : "warning"}>{item.eligibility.reason}</StatusChip> },
        { key: "assets", header: "Assets", render: (item) => item.asset_count },
      ]}
    />
  );
}

export function BaselineDetailPage() {
  const { baselineId = "" } = useParams();
  const baseline = useQuery({ queryKey: ["baseline", baselineId], queryFn: () => apiClient.getBaseline(baselineId) });
  const assets = useQuery({ queryKey: ["baseline-assets", baselineId], queryFn: () => apiClient.listBaselineAssets(baselineId) });
  const validation = useQuery({ queryKey: ["baseline-validation", baselineId], queryFn: () => apiClient.getBaselineValidation(baselineId) });
  const lineage = useQuery({ queryKey: ["baseline-lineage", baselineId], queryFn: () => apiClient.getBaselineLineage(baselineId) });
  return (
    <DetailLayout
      title={`Baseline ${baselineId}`}
      description="Materialized baseline assets, validation status, and publish explainability."
      summaryQuery={baseline}
      summary={(data) => (
        <KeyValueList items={[
          { label: "Status", value: data.status },
          { label: "Version", value: data.version },
          { label: "Eligibility", value: data.eligibility.reason },
          { label: "Assets", value: String(data.asset_count) },
        ]} />
      )}
      sidePanels={[
        <ExplainPanel key="validation" title="Validation summary">
          {validation.data ? <pre className="json-block">{JSON.stringify(validation.data, null, 2)}</pre> : <p>No validation report is available.</p>}
        </ExplainPanel>,
        <LineagePanel key="lineage" query={lineage} />,
      ]}
    >
      <SectionCard title="Baseline assets" subtitle="Ordered assets that back baseline publish execution.">
        <QueryState query={assets}>
          {(data) => (
            <DataTable
              rows={data.items}
              columns={[
                { key: "order", header: "Order", render: (item) => item.import_order },
                { key: "root", header: "Root object", render: (item) => item.root_object_id },
                { key: "rows", header: "Rows", render: (item) => item.row_count },
                { key: "checksum", header: "Checksum", render: (item) => item.checksum ?? "n/a" },
              ]}
            />
          )}
        </QueryState>
      </SectionCard>
    </DetailLayout>
  );
}

export function BaselineRefreshJobsPage() {
  const jobs = useQuery({ queryKey: ["baseline-refresh-jobs"], queryFn: () => apiClient.listBaselineRefreshJobs(), refetchInterval: 10000 });
  return (
    <EntityListPage
      title="Baseline refresh jobs"
      description="Track sanitized baseline materialization and refresh orchestration."
      query={jobs}
      rows={(data) => data}
      columns={[
        { key: "job", header: "Job", render: (job) => <Link to={`/baseline-refresh-jobs/${job.job_id}`}>{job.job_id}</Link> },
        { key: "status", header: "Status", render: (job) => <StatusChip tone={toneForStatus(job.status)}>{job.status}</StatusChip> },
        { key: "system", header: "System", render: (job) => job.system_id },
        { key: "baseline", header: "Baseline", render: (job) => job.baseline_id ?? "n/a" },
      ]}
    />
  );
}

export function BaselineRefreshJobDetailPage() {
  const { jobId = "" } = useParams();
  const job = useQuery({ queryKey: ["baseline-refresh-job", jobId], queryFn: () => apiClient.getBaselineRefreshJob(jobId) });
  const audit = useQuery({ queryKey: ["baseline-refresh-audit", jobId], queryFn: () => apiClient.listBaselineRefreshAudit(jobId) });
  return (
    <DetailLayout
      title={`Baseline refresh job ${jobId}`}
      description="Operational progress and technical audit for baseline materialization."
      summaryQuery={job}
      summary={(data) => (
        <KeyValueList items={[
          { label: "Status", value: data.status },
          { label: "System", value: data.system_id },
          { label: "Profile", value: data.dataset_profile_id },
          { label: "Baseline", value: data.baseline_id ?? "n/a" },
        ]} />
      )}
      sidePanels={[<TimelinePanel key="audit" title="Audit events" query={audit} />]}
    />
  );
}

export function RefreshSchedulesPage() {
  const systems = useSystems();
  const schedules = useQuery({ queryKey: ["refresh-schedules"], queryFn: () => apiClient.listRefreshSchedules() });
  const profiles = useQuery({ queryKey: ["all-profiles"], queryFn: () => apiClient.listDatasetProfiles() });
  const [form, setForm] = useState({
    systemId: "",
    datasetProfileId: "",
    targetEnvironmentType: "dev",
    intervalMinutes: 1440,
    createdBy: "steward@example.internal",
  });
  const createSchedule = useMutation({
    mutationFn: () => apiClient.createRefreshSchedule(form),
  });
  return (
    <div className="page-stack">
      <PageHeader title="Refresh schedules" description="Recurring baseline refresh creation without external scheduler coupling." />
      <div className="two-column">
        <SectionCard title="Create schedule" subtitle="Minimal recurring scheduling model for baseline refresh.">
          <div className="form-grid">
            <label>
              System
              <select value={form.systemId} onChange={(event) => setForm((current) => ({ ...current, systemId: event.target.value }))}>
                <option value="">Select system</option>
                {(systems.data ?? []).map((system) => <option key={system.system_id} value={system.system_id}>{system.name}</option>)}
              </select>
            </label>
            <label>
              Dataset profile
              <select value={form.datasetProfileId} onChange={(event) => setForm((current) => ({ ...current, datasetProfileId: event.target.value }))}>
                <option value="">Select profile</option>
                {(profiles.data ?? []).filter((profile) => !form.systemId || profile.system_id === form.systemId).map((profile) => (
                  <option key={profile.profile_id} value={profile.profile_id}>{profile.name}</option>
                ))}
              </select>
            </label>
            <label>
              Target environment type
              <select value={form.targetEnvironmentType} onChange={(event) => setForm((current) => ({ ...current, targetEnvironmentType: event.target.value }))}>
                {["dev", "test", "collaudo"].map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <label>
              Interval minutes
              <input type="number" value={form.intervalMinutes} onChange={(event) => setForm((current) => ({ ...current, intervalMinutes: Number(event.target.value) }))} />
            </label>
          </div>
          <div className="form-actions">
            <button className="primary-button" onClick={() => createSchedule.mutate()} disabled={!form.systemId || !form.datasetProfileId}>Create schedule</button>
          </div>
          {createSchedule.isSuccess ? <div className="success-state">Schedule {createSchedule.data.schedule_id} created.</div> : null}
          {createSchedule.isError ? <div className="error-state">{createSchedule.error.message}</div> : null}
        </SectionCard>
        <SectionCard title="Existing schedules" subtitle="Current recurring refresh dispatch model.">
          <QueryState query={schedules}>
            {(data) => (
              <DataTable
                rows={data}
                columns={[
                  { key: "schedule", header: "Schedule", render: (item) => item.schedule_id },
                  { key: "system", header: "System", render: (item) => item.system_id },
                  { key: "interval", header: "Interval", render: (item) => `${item.interval_minutes} min` },
                  { key: "status", header: "Status", render: (item) => <StatusChip tone={toneForStatus(item.status)}>{item.status}</StatusChip> },
                ]}
              />
            )}
          </QueryState>
        </SectionCard>
      </div>
    </div>
  );
}

function SystemSelector({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const systems = useSystems();
  return (
    <label className="stack-field">
      System
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Select system</option>
        {(systems.data ?? []).map((system) => <option key={system.system_id} value={system.system_id}>{system.name}</option>)}
      </select>
    </label>
  );
}

export function MetadataPage() {
  const [systemId, setSystemId] = useState("crm");
  const metadata = useQuery({ queryKey: ["metadata", systemId], queryFn: () => apiClient.listMetadataObjects(systemId), enabled: Boolean(systemId) });
  return <GovernanceListPage title="Metadata catalog" description="Canonical catalog objects by system." systemId={systemId} setSystemId={setSystemId} query={metadata} columns={[
    { key: "type", header: "Type", render: (item) => item.object_type },
    { key: "qualified", header: "Qualified name", render: (item) => item.qualified_name },
    { key: "logical", header: "Logical type", render: (item) => item.logical_data_type ?? "n/a" },
  ]} rows={(data) => data.items} />;
}

export function RelationshipsPage() {
  const [systemId, setSystemId] = useState("crm");
  const relationships = useQuery({ queryKey: ["relationships", systemId], queryFn: () => apiClient.listRelationships(systemId), enabled: Boolean(systemId) });
  return <GovernanceListPage title="Relationships" description="PK/FK visibility and relationship-aware governance context." systemId={systemId} setSystemId={setSystemId} query={relationships} columns={[
    { key: "type", header: "Type", render: (item) => item.relationship_type },
    { key: "source", header: "Source object", render: (item) => item.source_object_id },
    { key: "target", header: "Target object", render: (item) => item.target_object_id },
  ]} rows={(data) => data.items} />;
}

export function ClassificationsPage() {
  const [systemId, setSystemId] = useState("crm");
  const classifications = useQuery({ queryKey: ["classifications", systemId], queryFn: () => apiClient.listClassifications(systemId), enabled: Boolean(systemId) });
  return <GovernanceListPage title="Classifications" description="Sensitivity and explicit classification status visibility." systemId={systemId} setSystemId={setSystemId} query={classifications} columns={[
    { key: "tag", header: "Sensitivity tag", render: (item) => item.tag_name },
    { key: "object", header: "Object", render: (item) => item.object_id },
    { key: "status", header: "Status", render: (item) => <StatusChip tone={toneForStatus(item.classification_status)}>{item.classification_status}</StatusChip> },
  ]} rows={(data) => data.items} />;
}

export function PoliciesPage() {
  const [systemId, setSystemId] = useState("crm");
  const [targetMode, setTargetMode] = useState("");
  const policies = useQuery({ queryKey: ["policies", systemId, targetMode], queryFn: () => apiClient.listPolicies({ systemId, targetMode: targetMode || undefined }), enabled: Boolean(systemId) });
  return (
    <div className="page-stack">
      <PageHeader title="Transformation policies" description="Canonical vs legacy targeting visibility for migration, debugging, and enforcement." />
      <SectionCard title="Policy inventory" subtitle="Policies are filtered by system and optionally by target mode.">
        <div className="toolbar">
          <SystemSelector value={systemId} onChange={setSystemId} />
          <label className="stack-field">
            Target mode
            <select value={targetMode} onChange={(event) => setTargetMode(event.target.value)}>
              <option value="">All</option>
              <option value="canonical">canonical</option>
              <option value="legacy_fallback">legacy_fallback</option>
            </select>
          </label>
        </div>
        <QueryState query={policies}>
          {(data) => (
            <DataTable
              rows={data.items}
              columns={[
                { key: "policy", header: "Policy", render: (item) => item.policy_id },
                { key: "mode", header: "Target mode", render: (item) => <StatusChip tone={item.target_mode === "canonical" ? "success" : "warning"}>{item.target_mode}</StatusChip> },
                { key: "target", header: "Canonical object", render: (item) => item.canonical_object_id ?? item.legacy_object_name },
                { key: "column", header: "Column", render: (item) => item.column_name },
                { key: "transform", header: "Transformation", render: (item) => item.transformation_type },
              ]}
            />
          )}
        </QueryState>
      </SectionCard>
    </div>
  );
}

export function PolicyCoveragePage() {
  const [systemId, setSystemId] = useState("crm");
  const report = useQuery({ queryKey: ["policy-coverage", systemId], queryFn: () => apiClient.getPolicyCoverage(systemId), enabled: Boolean(systemId) });
  return (
    <div className="page-stack">
      <PageHeader title="Policy coverage" description="Make publish readiness and governance gaps explicit before data leaves the control plane." />
      <SectionCard title="Coverage report" subtitle="Blocking and informational gaps are separated for operator clarity.">
        <SystemSelector value={systemId} onChange={setSystemId} />
        <QueryState query={report}>
          {(data) => (
            <div className="two-column">
              <SummaryGrid>
                <SummaryMetric label="Publish ready" value={data.publish_ready ? "yes" : "no"} tone={data.publish_ready ? "accent" : "default"} />
                <SummaryMetric label="Blocking gaps" value={data.blocking_gap_count} />
                <SummaryMetric label="Informational gaps" value={data.informational_gap_count} />
              </SummaryGrid>
              <ExplainPanel title="Gap details" tone={data.publish_ready ? "default" : "warning"}>
                <ul className="bullet-list">
                  {data.gaps.map((gap) => (
                    <li key={`${gap.gap_type}-${gap.object_name}`}>{gap.object_name}: {gap.message}</li>
                  ))}
                </ul>
              </ExplainPanel>
            </div>
          )}
        </QueryState>
      </SectionCard>
    </div>
  );
}

export function GovernanceSummaryPage() {
  const [systemId, setSystemId] = useState("crm");
  const summary = useQuery({ queryKey: ["governance-summary", systemId], queryFn: () => apiClient.getGovernanceSummary(systemId), enabled: Boolean(systemId) });
  return <GovernanceListPage title="Governance summary" description="Composite read model that merges classification, policy, and coverage state per object." systemId={systemId} setSystemId={setSystemId} query={summary} columns={[
    { key: "object", header: "Object", render: (item) => item.qualified_name },
    { key: "classification", header: "Classification", render: (item) => item.classification_status },
    { key: "coverage", header: "Coverage", render: (item) => <StatusChip tone={toneForStatus(item.coverage_state)}>{item.coverage_state}</StatusChip> },
    { key: "policy", header: "Policy types", render: (item) => item.policy_types.join(", ") || "none" },
  ]} rows={(data) => data.items} />;
}

export function EngineCapabilitiesPage() {
  const capabilities = useQuery({ queryKey: ["engine-capabilities"], queryFn: () => apiClient.listEngineCapabilities() });
  return (
    <div className="page-stack">
      <PageHeader title="Engine capabilities" description="Release-readiness matrix for PostgreSQL and Oracle runtime adapters." />
      <SectionCard title="Capability matrix" subtitle="The UI uses this surface to hide or disable unsupported workflow slices.">
        <QueryState query={capabilities}>
          {(data) => (
            <DataTable
              rows={data.items}
              columns={[
                { key: "engine", header: "Engine", render: (item) => item.engine_type },
                { key: "metadata", header: "Metadata", render: (item) => <StatusChip tone={item.metadata_discovery_supported ? "success" : "danger"}>{item.metadata_discovery_supported ? "yes" : "no"}</StatusChip> },
                { key: "extract", header: "Extraction", render: (item) => <StatusChip tone={item.extraction_supported ? "success" : "danger"}>{item.extraction_supported ? "yes" : "no"}</StatusChip> },
                { key: "artifact", header: "Artifact publish", render: (item) => <StatusChip tone={item.artifact_publish_supported ? "success" : "danger"}>{item.artifact_publish_supported ? "yes" : "no"}</StatusChip> },
                { key: "baseline", header: "Baseline runtime", render: (item) => <StatusChip tone={item.baseline_publish_supported && item.baseline_refresh_supported ? "success" : "warning"}>{item.release_ready ? "full parity" : "partial"}</StatusChip> },
              ]}
            />
          )}
        </QueryState>
      </SectionCard>
    </div>
  );
}

export function NotFoundPage() {
  return (
    <div className="page-stack">
      <PageHeader title="Page not found" description="This route is not part of the current product shell." />
      <SectionCard title="Try another section">
        <p>Use the left navigation to move to a supported workflow.</p>
      </SectionCard>
    </div>
  );
}

function EntityListPage<T>({
  title,
  description,
  query,
  rows,
  columns,
}: {
  title: string;
  description: string;
  query: { isPending: boolean; error: Error | null; data: T | undefined };
  rows: (data: T) => unknown[];
  columns: Array<{ key: string; header: string; render: (item: any) => React.ReactNode }>;
}) {
  return (
    <div className="page-stack">
      <PageHeader title={title} description={description} />
      <SectionCard title={title} subtitle={description}>
        <QueryState query={query}>
          {(data) => <DataTable rows={rows(data)} columns={columns} />}
        </QueryState>
      </SectionCard>
    </div>
  );
}

function GovernanceListPage<T>({
  title,
  description,
  systemId,
  setSystemId,
  query,
  rows,
  columns,
}: {
  title: string;
  description: string;
  systemId: string;
  setSystemId: (value: string) => void;
  query: { isPending: boolean; error: Error | null; data: T | undefined };
  rows: (data: T) => unknown[];
  columns: Array<{ key: string; header: string; render: (item: any) => React.ReactNode }>;
}) {
  return (
    <div className="page-stack">
      <PageHeader title={title} description={description} />
      <SectionCard title={title} subtitle={description}>
        <SystemSelector value={systemId} onChange={setSystemId} />
        <QueryState query={query}>
          {(data) => <DataTable rows={rows(data)} columns={columns} />}
        </QueryState>
      </SectionCard>
    </div>
  );
}

function DetailLayout<T>({
  title,
  description,
  summaryQuery,
  summary,
  sidePanels,
  children,
}: {
  title: string;
  description: string;
  summaryQuery: { isPending: boolean; error: Error | null; data: T | undefined };
  summary: (data: T) => React.ReactNode;
  sidePanels: React.ReactNode[];
  children?: React.ReactNode;
}) {
  return (
    <div className="page-stack">
      <PageHeader title={title} description={description} />
      <div className="detail-layout">
        <SectionCard title="Summary" subtitle="Primary operational context for this entity.">
          <QueryState query={summaryQuery}>{(data) => <>{summary(data)}</>}</QueryState>
        </SectionCard>
        <div className="detail-sidebar">{sidePanels}</div>
      </div>
      {children}
    </div>
  );
}

function TimelinePanel({
  title,
  query,
}: {
  title: string;
  query: { isPending: boolean; error: Error | null; data: Array<{ event_type: string; created_at: string; actor: string }> | undefined };
}) {
  return (
    <ExplainPanel title={title}>
      <QueryState query={query}>
        {(data) => (
          <ul className="timeline-list">
            {data.map((item) => (
              <li key={`${item.event_type}-${item.created_at}`}>
                <strong>{titleCase(item.event_type)}</strong>
                <span>{formatDateTime(item.created_at)}</span>
                <small>{item.actor}</small>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </ExplainPanel>
  );
}

function LineagePanel({
  query,
}: {
  query: { isPending: boolean; error: Error | null; data: { items: Array<{ event_type: string; source_type: string; target_type: string }> } | undefined };
}) {
  return (
    <ExplainPanel title="Lineage">
      <QueryState query={query}>
        {(data) => (
          <ul className="timeline-list">
            {data.items.map((item, index) => (
              <li key={`${item.event_type}-${index}`}>
                <strong>{titleCase(item.event_type)}</strong>
                <span>{item.source_type} → {item.target_type}</span>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </ExplainPanel>
  );
}
