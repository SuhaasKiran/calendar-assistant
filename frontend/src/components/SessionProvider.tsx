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

function oauthErrorBanner(errorCode: string): string {
  switch (errorCode) {
    case "token_exchange_failed":
    case "userinfo_failed":
      return "Sign-in failed due to a provider error. Please try again.";
    case "invalid_state":
      return "Sign-in failed because session validation failed. Please retry.";
    case "missing_code":
      return "Sign-in did not complete. Please try again.";
    case "server_not_configured":
      return "Sign-in is temporarily unavailable. Please contact support.";
    default:
      return "Sign-in failed. Please try again.";
  }
}

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
      setOauthBanner(oauthErrorBanner(error));
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
