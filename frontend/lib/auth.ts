/**
 * auth.ts
 *
 * Small client-side auth utility:
 *   - getApiBaseUrl()       reads the API base URL from env
 *   - getSession() / setSession() / clearSession()
 *                           manage the {token, userId, username, role} object
 *                           stored in localStorage
 *   - login(username, pw)   calls POST /auth/login, stores the session, returns it
 *   - logout()              calls POST /auth/logout (best-effort), clears local state
 *   - apiFetch(path, opts)  thin wrapper around fetch() that automatically attaches
 *                           the Authorization: Bearer <token> header
 *
 * The session token is stored in localStorage. Trade-off:
 *   - simple, persists across reloads and tabs
 *   - vulnerable to XSS if the app ever has an XSS bug
 * For a production deployment this would migrate to an HTTP-only cookie set
 * by the backend on the login response.
 */

const SESSION_KEY = "luna.session";

export interface Session {
  token: string;
  userId: string;
  username: string;
  role: string;
}

/* ── Config ─────────────────────────────────────────────────────────── */

export function getApiBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (!url) {
    throw new Error(
      "NEXT_PUBLIC_API_URL is not set. Copy .env.local.example to .env.local and fill in the API URL."
    );
  }
  return url.replace(/\/$/, ""); // strip trailing slash if present
}

/* ── Session storage ────────────────────────────────────────────────── */

export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function setSession(session: Session): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(SESSION_KEY);
}

/* ── Auth API calls ─────────────────────────────────────────────────── */

export async function login(username: string, password: string): Promise<Session> {
  const res = await fetch(`${getApiBaseUrl()}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  // Try to parse the body for a useful error message even on failure
  let payload: Record<string, unknown> = {};
  try {
    payload = await res.json();
  } catch {
    // ignore parse error
  }

  if (!res.ok) {
    const msg = (payload.error as string) || `Login failed (${res.status})`;
    throw new Error(msg);
  }

  const session: Session = {
    token: payload.sessionToken as string,
    userId: payload.userId as string,
    username: payload.username as string,
    role: (payload.role as string) || "doctor",
  };
  setSession(session);
  return session;
}

export async function logout(): Promise<void> {
  const session = getSession();
  if (!session) return;

  // Best-effort backend logout; clear local state regardless of network result
  try {
    await fetch(`${getApiBaseUrl()}/auth/logout`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${session.token}`,
        "Content-Type": "application/json",
      },
    });
  } catch {
    // network failure is non-blocking — we still clear local state
  } finally {
    clearSession();
  }
}

/* ── Authenticated fetch wrapper ────────────────────────────────────── */

/**
 * Wrapper around fetch() that:
 *   - resolves relative paths against NEXT_PUBLIC_API_URL
 *   - attaches the Authorization: Bearer <token> header automatically
 *   - throws a descriptive Error on non-2xx responses
 *
 * Use for any call to a protected backend endpoint:
 *   const data = await apiFetch("/patients");
 *   const result = await apiFetch(`/patients/${id}/diagnose`, {
 *     method: "POST",
 *     body: JSON.stringify({ s3Key }),
 *   });
 */
export async function apiFetch<T = unknown>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const session = getSession();
  if (!session) {
    throw new Error("Not authenticated");
  }

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${session.token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const url = path.startsWith("http") ? path : `${getApiBaseUrl()}${path}`;
  const res = await fetch(url, { ...init, headers });

  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = (body.error as string) || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(`API ${res.status}: ${detail}`);
  }

  // 204 No Content
  if (res.status === 204) return undefined as T;

  return (await res.json()) as T;
}
