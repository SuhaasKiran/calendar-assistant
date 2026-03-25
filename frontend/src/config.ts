/**
 * Base URL for the Calendar Assistant API (`VITE_API_BASE_URL`).
 * In dev, defaults to same-origin (empty) so Vite proxies `/auth` and `/chat` to FastAPI;
 * session cookies then match `http://localhost:5173` after OAuth redirects to `localhost:8000`.
 */
export function getApiBase(): string {
  const raw = import.meta.env.VITE_API_BASE_URL;
  if (typeof raw === "string" && raw.length > 0) {
    return raw.replace(/\/$/, "");
  }
  if (import.meta.env.DEV) {
    return "";
  }
  return "http://localhost:8000";
}
