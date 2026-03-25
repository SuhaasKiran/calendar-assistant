import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { fetchMe, logout as apiLogout } from "../api/auth";
import { SessionContext } from "../context/SessionContext";
import type { User } from "../api/auth";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [oauthBanner, setOauthBanner] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    const u = await fetchMe();
    setUser(u);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const login = params.get("login");
    const error = params.get("error");
    if (login === "ok") {
      setOauthBanner("Signed in successfully.");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (error) {
      setOauthBanner(`Sign-in failed: ${error}`);
      window.history.replaceState({}, "", window.location.pathname);
    }

    let cancelled = false;
    (async () => {
      try {
        const u = await fetchMe();
        if (!cancelled) setUser(u);
      } catch {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const clearOAuthBanner = useCallback(() => setOauthBanner(null), []);

  const value = useMemo(
    () => ({
      user,
      loading,
      oauthBanner,
      clearOAuthBanner,
      refetch,
      logout,
    }),
    [user, loading, oauthBanner, clearOAuthBanner, refetch, logout],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}
