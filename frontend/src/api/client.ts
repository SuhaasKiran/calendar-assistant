import { getApiBase } from "../config";

/** `fetch` to the API with cookies (same-origin in dev via Vite proxy, or credentialed cross-origin). */
const API_TIMEOUT_MS = 30000;
const MAX_RETRIES = 2;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function shouldRetry(response: Response | null, error: unknown, method: string): boolean {
  // Retry safe methods only; avoid duplicate side effects.
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) return false;
  if (error instanceof DOMException && error.name === "AbortError") return true;
  if (response) return response.status === 429 || response.status >= 500;
  return false;
}

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const base = getApiBase();
  const p = path.startsWith("/") ? path : `/${path}`;
  const url = base ? `${base}${p}` : p;
  const method = (init?.method || "GET").toUpperCase();

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
    let response: Response | null = null;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
    try {
      response = await fetch(url, {
        ...init,
        credentials: "include",
        signal: init?.signal ?? controller.signal,
      });
      if (!shouldRetry(response, null, method) || attempt === MAX_RETRIES) return response;
    } catch (error) {
      if (!shouldRetry(null, error, method) || attempt === MAX_RETRIES) throw error;
    } finally {
      window.clearTimeout(timeout);
    }
    await sleep(250 * 2 ** attempt);
  }

  throw new Error("Network request failed");
}
