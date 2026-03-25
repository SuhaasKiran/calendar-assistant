import { getApiBase } from "../config";

/** `fetch` to the API with cookies (same-origin in dev via Vite proxy, or credentialed cross-origin). */
export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const base = getApiBase();
  const p = path.startsWith("/") ? path : `/${path}`;
  const url = base ? `${base}${p}` : p;
  return fetch(url, { ...init, credentials: "include" });
}
