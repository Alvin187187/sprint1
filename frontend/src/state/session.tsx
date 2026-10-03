import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api } from "../lib/api";
import type { Session, Usage } from "../lib/types";

interface SessionState {
  status: "loading" | "signed-out" | "signed-in";
  session: Session | null;
  usage: Usage | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  setUsage: (usage: Usage) => void;
  refreshUsage: () => Promise<void>;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionState["status"]>("loading");
  const [session, setSession] = useState<Session | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);

  const refreshUsage = useCallback(async () => {
    try {
      setUsage(await api.usage());
    } catch {
      // A failed usage read must not block the chat; the meter just goes quiet.
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await api.me();
        if (cancelled) return;
        setSession(next);
        setStatus("signed-in");
        void refreshUsage();
      } catch {
        if (!cancelled) setStatus("signed-out");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshUsage]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const next = await api.login(email, password);
      setSession(next);
      setStatus("signed-in");
      await refreshUsage();
    },
    [refreshUsage],
  );

  const signOut = useCallback(async () => {
    await api.logout().catch(() => undefined);
    setSession(null);
    setUsage(null);
    setStatus("signed-out");
  }, []);

  const value = useMemo<SessionState>(
    () => ({ status, session, usage, signIn, signOut, setUsage, refreshUsage }),
    [status, session, usage, signIn, signOut, refreshUsage],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}
