import { createContext, useContext, useMemo, useState, type PropsWithChildren } from "react";

export type SessionRole = "developer_tester" | "data_steward" | "admin";

type SessionContextValue = {
  role: SessionRole;
  setRole: (role: SessionRole) => void;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: PropsWithChildren) {
  const [role, setRole] = useState<SessionRole>("developer_tester");
  const value = useMemo(() => ({ role, setRole }), [role]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (context === null) {
    throw new Error("useSession must be used within SessionProvider");
  }
  return context;
}
