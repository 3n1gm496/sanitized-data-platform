import { Link, NavLink, Outlet } from "react-router-dom";
import { useSession, type SessionRole } from "../app/session";

type NavItem = {
  to: string;
  label: string;
  roles: SessionRole[];
};

type NavGroup = {
  label: string;
  items: NavItem[];
};

type AppShellProps = {
  navGroups: NavGroup[];
};

const roles: SessionRole[] = ["developer_tester", "data_steward", "admin"];

export function AppShell({ navGroups }: AppShellProps) {
  const { role, setRole } = useSession();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar__brand">
          <Link to="/">Sanitized Data Platform</Link>
          <p>Governed non-prod data delivery</p>
        </div>
        <nav className="sidebar__nav">
          {navGroups.map((group) => {
            const items = group.items.filter((item) => item.roles.includes(role));
            if (items.length === 0) return null;
            return (
              <div key={group.label} className="sidebar__group">
                <p className="sidebar__group-title">{group.label}</p>
                {items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) => (isActive ? "nav-link nav-link--active" : "nav-link")}
                  >
                    {item.label}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>
      </aside>
      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">Role-aware console</p>
            <h2>Operational visibility with guardrails</h2>
          </div>
          <label className="role-switcher">
            Active role
            <select value={role} onChange={(event) => setRole(event.target.value as SessionRole)}>
              {roles.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </header>
        <div className="content">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
