import { getApiBase } from "../config";
import { apiFetch } from "./client";

export type User = {
  id: number;
  google_sub: string;
  email: string | null;
  timezone: string;
};

/** Returns the current user, or `null` if not authenticated (401). */
export async function fetchMe(): Promise<User | null> {
  const r = await apiFetch("/auth/me");
  if (r.status === 401) return null;
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<User>;
}

export async function logout(): Promise<void> {
  const r = await apiFetch("/auth/logout", { method: "POST" });
  if (!r.ok && r.status !== 204) {
    const t = await r.text();
    throw new Error(t || "Logout failed");
  }
}

/** Path or URL for browser navigation — do not use `fetch`. */
export function signInUrl(): string {
  const base = getApiBase();
  return base ? `${base}/auth/google/start` : "/auth/google/start";
}
