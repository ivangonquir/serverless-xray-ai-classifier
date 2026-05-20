/**
 * auth.ts
 *
 * Small client-side auth utility:
 *   - getApiBaseUrl()       reads the API base URL from env
 *   - getSession() / setSession() / clearSession()
 *                           manage the {token, userId, username, role} object
 *                           stored in either localStorage (persistent) or
 *                           sessionStorage (cleared on tab close), driven by
 *                           the "Remember session" checkbox on login.
 *   - login(username, pw, remember)
 *                           calls POST /auth/login, stores the session, returns it
 *   - logout()              calls POST /auth/logout (best-effort), clears local state
 *   - apiFetch(path, opts)  thin wrapper around fetch() that automatically attaches
 *                           the Authorization: Bearer <token> header and handles
 *                           401 responses by clearing the session and redirecting
 *                           to /login.
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
  const url =
    process.env.NEXT_PUBLIC_API_URL ||
    "https://elomb6x6wi.execute-api.eu-west-1.amazonaws.com/prod";
  if (!process.env.NEXT_PUBLIC_API_URL && typeof window !== "undefined") {
    console.warn(
      "[LUNA] NEXT_PUBLIC_API_URL not set — falling back to default. Set it in .env.local."
    );
  }
  return url.replace(/\/$/, "");
}

/* ── Session storage ────────────────────────────────────────────────── */

/**
 * Reads the session from whichever storage holds it.
 * Checks sessionStorage first (tab-scoped), then localStorage (persistent).
 */
export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw =
      window.sessionStorage.getItem(SESSION_KEY) ||
      window.localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

/**
 * Writes the session to either localStorage or sessionStorage.
 *
 *  - remember = true  → localStorage (persists across browser restarts)
 *  - remember = false → sessionStorage (cleared when the tab closes)
 *
 * Always clears the opposite store first so we never end up with two
 * different sessions in the two storages.
 */
export function setSession(session: Session, remember: boolean): void {
  if (typeof window === "undefined") return;
  const serialized = JSON.stringify(session);
  if (remember) {
    window.localStorage.setItem(SESSION_KEY, serialized);
    window.sessionStorage.removeItem(SESSION_KEY);
  } else {
    window.sessionStorage.setItem(SESSION_KEY, serialized);
    window.localStorage.removeItem(SESSION_KEY);
  }
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(SESSION_KEY);
  window.sessionStorage.removeItem(SESSION_KEY);
}

/* ── Auth API calls ─────────────────────────────────────────────────── */

export async function login(
  username: string,
  password: string,
  remember: boolean = false
): Promise<Session> {
  const res = await fetch(`${getApiBaseUrl()}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

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
  setSession(session, remember);
  return session;
}

export async function logout(): Promise<void> {
  const session = getSession();
  if (!session) return;

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

export async function apiFetch<T = unknown>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const session = getSession();
  if (!session) {
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
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
    if (res.status === 401) {
      clearSession();
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
      throw new Error("Session expired. Please sign in again.");
    }

    let detail = "";
    try {
      const body = await res.json();
      detail = (body.error as string) || JSON.stringify(body);
    } catch {
      detail = await res.text();
    }
    throw new Error(`API ${res.status}: ${detail}`);
  }

  if (res.status === 204) return undefined as T;

  return (await res.json()) as T;
}