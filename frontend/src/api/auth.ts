import { getApiBase } from "../config";
import { apiFetch } from "./client";
import type { ApiError } from "./chat";

export type User = {
  id: number;
  google_sub: string;
  email: string | null;
  timezone: string;
};

const GENERIC_SERVER_ERROR = "Something went wrong on our side. Please try again.";

function authErrorMessage(status: number, fallback: string): string {
  if (status >= 500) return GENERIC_SERVER_ERROR;
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You do not have permission to perform this action.";
  return fallback;
}

async function toAuthError(response: Response, fallback: string): Promise<ApiError> {
  const err = new Error(authErrorMessage(response.status, fallback)) as ApiError;
  err.status = response.status;
  try {
    const parsed = (await response.json()) as {
      detail?: unknown;
      code?: unknown;
      retryable?: unknown;
      request_id?: unknown;
    };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      err.message = authErrorMessage(response.status, parsed.detail.trim());
    }
    if (typeof parsed.code === "string") err.code = parsed.code;
    if (typeof parsed.retryable === "boolean") err.retryable = parsed.retryable;
    if (typeof parsed.request_id === "string") err.requestId = parsed.request_id;
  } catch {
    // Ignore non-JSON bodies.
  }
  return err;
}

/** Returns the current user, or `null` if not authenticated (401). */
export async function fetchMe(): Promise<User | null> {
  const r = await apiFetch("/auth/me");
  if (r.status === 401) return null;
  if (!r.ok) {
    throw await toAuthError(r, r.statusText || "Failed to fetch session");
  }
  return r.json() as Promise<User>;
}

export async function logout(): Promise<void> {
  const r = await apiFetch("/auth/logout", { method: "POST" });
  if (!r.ok && r.status !== 204) {
    throw await toAuthError(r, "Logout failed");
  }
}

/** Path or URL for browser navigation — do not use `fetch`. */
export function signInUrl(): string {
  const base = getApiBase();
  return base ? `${base}/auth/google/start` : "/auth/google/start";
}
