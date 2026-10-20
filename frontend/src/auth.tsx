import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, ApiError, hasSession, resetCsrf } from "./api";
import type { AuthState, MyPermissions } from "./types";

interface Auth {
  loading: boolean;
  state: AuthState | null; // null = not logged in
  perms: MyPermissions | null; // only after two-step verification (if needed)
  can: (code: string) => boolean;
  refresh: () => Promise<void>;
  login: (email: string, password: string) => Promise<AuthState>;
  verify: (token: string) => Promise<AuthState>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<Auth | null>(null);

/** Logged in and allowed past two-step verification. */
export function isReady(state: AuthState | null): boolean {
  return !!state && (!state.mfa.required || state.mfa.verified);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [state, setState] = useState<AuthState | null>(null);
  const [perms, setPerms] = useState<MyPermissions | null>(null);

  const loadPerms = useCallback(async (s: AuthState | null) => {
    setPerms(isReady(s) ? await api<MyPermissions>("/api/rbac/me/permissions/") : null);
  }, []);

  const refresh = useCallback(async () => {
    try {
      if (!(await hasSession())) {
        setState(null);
        setPerms(null);
        return;
      }
      const s = await api<AuthState>("/api/auth/me/");
      setState(s);
      await loadPerms(s);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        setState(null);
        setPerms(null);
      } else {
        throw e;
      }
    } finally {
      setLoading(false);
    }
  }, [loadPerms]);

  useEffect(() => {
    refresh().catch(() => setLoading(false));
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const s = await api<AuthState>("/api/auth/login/", { method: "POST", body: { email, password } });
    resetCsrf(); // Django gives a new token after login
    setState(s);
    await loadPerms(s);
    return s;
  }, [loadPerms]);

  const verify = useCallback(async (token: string) => {
    const s = await api<AuthState>("/api/auth/mfa/verify/", { method: "POST", body: { token } });
    resetCsrf();
    setState(s);
    await loadPerms(s);
    return s;
  }, [loadPerms]);

  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout/", { method: "POST" });
    } finally {
      resetCsrf();
      setState(null);
      setPerms(null);
    }
  }, []);

  const value = useMemo<Auth>(() => ({
    loading, state, perms, refresh, login, verify, logout,
    can: (code: string) => !!perms && perms.usable.includes(code),
  }), [loading, state, perms, refresh, login, verify, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
