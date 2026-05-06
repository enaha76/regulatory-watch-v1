import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "@/app/App";
import { AuthProvider } from "@/app/auth";
import "@/styles/index.css";

// AuthProvider wraps everything: it blocks the UI on a "Signing
// you in…" splash until Keycloak completes its login redirect, then
// renders App with a real user identity available via useAuth().
//
// StrictMode is intentionally OFF here. Keycloak's adapter does not
// tolerate the dev-mode double-mount (it tries to re-handle the
// redirect's auth-code and crashes the second time). We accept the
// loss of strict-mode warnings on this layer in exchange for a
// working OIDC flow; views inside App still benefit from StrictMode
// since they don't touch the adapter directly.
createRoot(document.getElementById("root")!).render(
  <AuthProvider>
    <StrictMode>
      <App />
    </StrictMode>
  </AuthProvider>,
);
