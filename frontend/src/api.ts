/**
 * Small API client for the Django backend (same address, session cookie).
 *
 * - Every change (POST/PATCH/PUT/DELETE) sends the CSRF token in X-CSRFToken.
 *   The cookie is HttpOnly, so the token comes from GET /api/auth/csrf/.
 * - Django changes the token at login and logout; call resetCsrf() then.
 * - If a change is refused because the token is old, it is fetched again and
 *   the request is retried once.
 */
export class ApiError extends Error {
  status: number;
  code?: string;
  data: unknown;

  constructor(status: number, message: string, code?: string, data?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);
let csrfToken: string | null = null;

export function resetCsrf(): void {
  csrfToken = null;
}

async function fetchCsrf(): Promise<{ csrfToken: string; authenticated: boolean }> {
  const res = await fetch("/api/auth/csrf/", { credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, "Could not reach the server.");
  const body = await res.json();
  csrfToken = body.csrfToken as string;
  return body;
}

async function getCsrf(): Promise<string> {
  if (!csrfToken) await fetchCsrf();
  return csrfToken as string;
}

/** Is anyone logged in on this browser? Asks without causing a 403 error. */
export async function hasSession(): Promise<boolean> {
  return (await fetchCsrf()).authenticated === true;
}

/** Turn a Django/DRF error body into one readable sentence. */
export function errorMessage(data: unknown, fallback: string): string {
  if (!data || typeof data !== "object") return fallback;
  const d = data as Record<string, unknown>;
  if (typeof d.detail === "string") return d.detail;
  const parts: string[] = [];
  for (const [key, value] of Object.entries(d)) {
    const text = Array.isArray(value) ? value.join(" ") : typeof value === "string" ? value : "";
    if (text) parts.push(key === "non_field_errors" || key === "duplicate" ? text : `${key}: ${text}`);
  }
  return parts.join(" ") || fallback;
}

export async function api<T = unknown>(path: string, options: { method?: string; body?: unknown } = {}, retried = false): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE.has(method)) headers["X-CSRFToken"] = await getCsrf();

  const res = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const csrfFailure = res.status === 403 && /csrf/i.test(text);
    if (csrfFailure && UNSAFE.has(method) && !retried) {
      resetCsrf();
      return api<T>(path, options, true);
    }
    const code = data && typeof data === "object" ? ((data as Record<string, unknown>).code as string | undefined) : undefined;
    throw new ApiError(res.status, errorMessage(data, `The server answered ${res.status}.`), code, data);
  }
  return data as T;
}

/** "12.5" -> "$12.50" (NZ format). Money arrives from the API as exact strings. */
export function money(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  return n.toLocaleString("en-NZ", { style: "currency", currency: "NZD", currencyDisplay: "narrowSymbol" });
}

export function quantity(value: string | number, unit: string): string {
  const n = Number(value);
  const text = Number.isInteger(n) ? String(n) : String(n).replace(/0+$/, "");
  if (unit === "kg") return `${text} kg`;
  if (unit === "pack") return `${text} pack${n === 1 ? "" : "s"}`;
  return text;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString("en-NZ", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
