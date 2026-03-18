import { createBrowserRouter } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import {
  ArtifactDetailPage,
  ArtifactPublishJobDetailPage,
  ArtifactPublishJobsPage,
  BaselineDetailPage,
  BaselineRefreshJobDetailPage,
  BaselineRefreshJobsPage,
  BaselinesPage,
  ClassificationsPage,
  EngineCapabilitiesPage,
  ExtractionJobDetailPage,
  ExtractionJobsPage,
  ExtractionPreviewPage,
  GovernanceSummaryPage,
  HomePage,
  MetadataPage,
  NotFoundPage,
  PoliciesPage,
  PolicyCoveragePage,
  PublishJobDetailPage,
  PublishJobsPage,
  PublishRequestPage,
  RefreshSchedulesPage,
  RelationshipsPage,
} from "../pages";

const navGroups = [
  {
    label: "Home",
    items: [{ to: "/", label: "Overview", roles: ["developer_tester", "data_steward", "admin"] }],
  },
  {
    label: "Publish",
    items: [
      { to: "/publish/new", label: "Request publish", roles: ["developer_tester", "admin"] },
      { to: "/publish/jobs", label: "Publish jobs", roles: ["developer_tester", "data_steward", "admin"] },
    ],
  },
  {
    label: "Extraction",
    items: [
      { to: "/extraction/preview", label: "Plan & run", roles: ["developer_tester", "admin"] },
      { to: "/extraction/jobs", label: "Extraction jobs", roles: ["developer_tester", "data_steward", "admin"] },
      { to: "/artifact-publish/jobs", label: "Artifact publish", roles: ["developer_tester", "data_steward", "admin"] },
    ],
  },
  {
    label: "Baselines",
    items: [
      { to: "/baselines", label: "Baselines", roles: ["developer_tester", "data_steward", "admin"] },
      { to: "/baseline-refresh-jobs", label: "Refresh jobs", roles: ["data_steward", "admin"] },
      { to: "/refresh-schedules", label: "Schedules", roles: ["data_steward", "admin"] },
    ],
  },
  {
    label: "Governance",
    items: [
      { to: "/governance/metadata", label: "Metadata", roles: ["data_steward", "admin"] },
      { to: "/governance/relationships", label: "Relationships", roles: ["data_steward", "admin"] },
      { to: "/governance/classifications", label: "Classifications", roles: ["data_steward", "admin"] },
      { to: "/governance/policies", label: "Policies", roles: ["data_steward", "admin"] },
      { to: "/governance/policy-coverage", label: "Coverage", roles: ["data_steward", "admin"] },
      { to: "/governance/summary", label: "Summary", roles: ["data_steward", "admin"] },
    ],
  },
  {
    label: "Observability",
    items: [
      { to: "/observability/engine-capabilities", label: "Engine capabilities", roles: ["developer_tester", "data_steward", "admin"] },
    ],
  },
] as const;

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell navGroups={navGroups as never} />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "/publish/new", element: <PublishRequestPage /> },
      { path: "/publish/jobs", element: <PublishJobsPage /> },
      { path: "/publish/jobs/:jobId", element: <PublishJobDetailPage /> },
      { path: "/extraction/preview", element: <ExtractionPreviewPage /> },
      { path: "/extraction/jobs", element: <ExtractionJobsPage /> },
      { path: "/extraction/jobs/:jobId", element: <ExtractionJobDetailPage /> },
      { path: "/artifacts/:artifactId", element: <ArtifactDetailPage /> },
      { path: "/artifact-publish/jobs", element: <ArtifactPublishJobsPage /> },
      { path: "/artifact-publish/jobs/:jobId", element: <ArtifactPublishJobDetailPage /> },
      { path: "/baselines", element: <BaselinesPage /> },
      { path: "/baselines/:baselineId", element: <BaselineDetailPage /> },
      { path: "/baseline-refresh-jobs", element: <BaselineRefreshJobsPage /> },
      { path: "/baseline-refresh-jobs/:jobId", element: <BaselineRefreshJobDetailPage /> },
      { path: "/refresh-schedules", element: <RefreshSchedulesPage /> },
      { path: "/governance/metadata", element: <MetadataPage /> },
      { path: "/governance/relationships", element: <RelationshipsPage /> },
      { path: "/governance/classifications", element: <ClassificationsPage /> },
      { path: "/governance/policies", element: <PoliciesPage /> },
      { path: "/governance/policy-coverage", element: <PolicyCoveragePage /> },
      { path: "/governance/summary", element: <GovernanceSummaryPage /> },
      { path: "/observability/engine-capabilities", element: <EngineCapabilitiesPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
