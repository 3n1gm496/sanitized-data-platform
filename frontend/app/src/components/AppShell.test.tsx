import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AppShell } from "./AppShell";
import { SessionProvider } from "../app/session";

const navGroups = [
  {
    label: "Publish",
    items: [{ to: "/publish/new", label: "Request publish", roles: ["developer_tester", "admin"] }],
  },
  {
    label: "Governance",
    items: [{ to: "/governance/policies", label: "Policies", roles: ["data_steward", "admin"] }],
  },
] as const;

describe("AppShell", () => {
  afterEach(() => cleanup());

  it("hides governance links for developer/tester role", () => {
    render(
      <SessionProvider>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <AppShell navGroups={navGroups as never} />
        </MemoryRouter>
      </SessionProvider>,
    );

    expect(screen.getByText("Request publish")).toBeInTheDocument();
    expect(screen.queryByText("Policies")).not.toBeInTheDocument();
  });

  it("shows governance links when switched to admin", async () => {
    const user = userEvent.setup();
    render(
      <SessionProvider>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <AppShell navGroups={navGroups as never} />
        </MemoryRouter>
      </SessionProvider>,
    );

    await user.selectOptions(screen.getByLabelText("Active role"), "admin");

    expect(screen.getByText("Policies")).toBeInTheDocument();
  });
});
