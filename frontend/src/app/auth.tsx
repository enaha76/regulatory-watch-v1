import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import Keycloak from "keycloak-js";

// ─────────────────────────────────────────────────────────────────────
// Keycloak / OIDC integration.
//
// One Keycloak singleton lives at module scope so we don't accidentally
// re-init on every render. The provider mounts it on first paint and
// blocks the UI on a "Signing you in…" splash until login completes.
//
// All API fetches that need a Bearer token go through `authFetch()`
// below (the API client uses it implicitly).
// ─────────────────────────────────────────────────────────────────────

const KEYCLOAK_URL =
  (import.meta as any).env?.VITE_KEYCLOAK_URL || "http://localhost:8085";
const KEYCLOAK_REALM =
  (import.meta as any).env?.VITE_KEYCLOAK_REALM || "regwatch";
const KEYCLOAK_CLIENT_ID =
  (import.meta as any).env?.VITE_KEYCLOAK_CLIENT_ID || "regwatch-frontend";

// Module-level singleton — Keycloak's adapter must not be instantiated
// twice in the same page or it'll crash mid-redirect.
const keycloak = new Keycloak({
  url: KEYCLOAK_URL,
  realm: KEYCLOAK_REALM,
  clientId: KEYCLOAK_CLIENT_ID,
});

let keycloakInitPromise: Promise<boolean> | null = null;
function initKeycloak(): Promise<boolean> {
  if (!keycloakInitPromise) {
    keycloakInitPromise = keycloak.init({
      onLoad: "login-required",
      checkLoginIframe: false,   // simpler dev flow, no iframe shenanigans
      pkceMethod: "S256",
      // We use HashRouter, so the route lives in the URL fragment.
      // Default response_mode=fragment would put OIDC params in the
      // hash and the router would 404 on `#state=…&code=…` before
      // Keycloak gets to clean it up. Send them as query instead.
      responseMode: "query",
    });
  }
  return keycloakInitPromise;
}

// ── Public API ────────────────────────────────────────────────────────

export interface AuthUser {
  /** Keycloak `sub` — stable opaque ID. */
  sub: string;
  /** Email claim. The backend uses this to scope queries. */
  email: string;
  /** Optional friendly display name. */
  name?: string;
  /** Realm roles. */
  roles: string[];
}

interface AuthContextValue {
  user: AuthUser | null;
  ready: boolean;
  /** Best-effort token; auto-refreshed by `authFetch` before use. */
  token: () => string | undefined;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);

  // Map the parsed token into a typed user object. Returns null when
  // the token isn't present or can't be parsed.
  const buildUser = useCallback((): AuthUser | null => {
    const t: any = keycloak.tokenParsed;
    if (!t) return null;
    const realmRoles: string[] = t?.realm_access?.roles ?? [];
    return {
      sub: t.sub,
      email: t.email ?? t.preferred_username ?? "",
      name: t.name ?? t.preferred_username,
      roles: realmRoles,
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    initKeycloak()
      .then((authenticated) => {
        if (!mounted) return;
        if (!authenticated) {
          // Should not happen with onLoad="login-required" — Keycloak
          // would have redirected. Belt-and-suspenders log.
          console.warn("Keycloak init returned not authenticated");
        }
        setUser(buildUser());
        setReady(true);

        // Refresh the token in the background a minute before expiry.
        // tokenParsed.exp is in seconds-since-epoch.
        keycloak.onTokenExpired = () => {
          keycloak
            .updateToken(60)
            .then(() => setUser(buildUser()))
            .catch(() => {
              // Refresh failed — bounce to login.
              keycloak.login();
            });
        };
      })
      .catch((err) => {
        console.error("Keycloak init failed", err);
        if (mounted) setReady(true); // unblock UI; user stays null
      });
    return () => {
      mounted = false;
    };
  }, [buildUser]);

  const value: AuthContextValue = {
    user,
    ready,
    token: () => keycloak.token,
    logout: () => {
      keycloak.logout({
        redirectUri: window.location.origin + "/",
      });
    },
  };

  if (!ready) {
    return (
      <div className="min-h-svh flex flex-col items-center justify-center bg-background">
        <div className="size-3 rounded-full border-2 border-primary border-t-transparent animate-spin mb-3" />
        <p className="text-muted-foreground" style={{ fontSize: "var(--text-sm)" }}>
          Signing you in…
        </p>
      </div>
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ── authFetch — drop-in replacement for global fetch ──────────────────
//
// Auto-attaches Bearer token. Auto-refreshes on 401 once. Call sites
// (the API client) use this transparently — they don't need to know
// about Keycloak.

export async function authFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  // Try to refresh the token if it's about to expire. 30s buffer keeps
  // long-running requests from racing the expiry.
  try {
    await keycloak.updateToken(30);
  } catch {
    // Refresh failed — let the request go anyway; it'll 401 and the
    // caller can decide how to recover.
  }

  const headers = new Headers(init.headers);
  if (keycloak.token) {
    headers.set("Authorization", `Bearer ${keycloak.token}`);
  }
  return fetch(input, { ...init, headers });
}

/**
 * Direct access to the Keycloak instance — escape hatch for things
 * the AuthProvider doesn't expose. Avoid using this from view code;
 * prefer `useAuth()`.
 */
export { keycloak as keycloakInstance };
