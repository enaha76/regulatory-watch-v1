import { useState, useEffect } from "react";
import { useNavigate, useLocation, Outlet } from "react-router";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/app/components/ui/sidebar";
import {
  Inbox,
  Archive,
  Target,
  Globe,
  Search,
  Coins,
  LogOut,
  Moon,
  Sun,
} from "lucide-react";
import { Badge } from "@/app/components/ui/badge";
import {
  NotificationsProvider,
  useNotifications,
} from "@/app/notifications";
import { SystemHealthIndicator } from "@/app/components/system-health";
import { useAuth } from "@/app/auth";
import logoIcon from "@/assets/logo-icon.jpeg";

// The provider has to live inside a router context (because its toast
// items use `useNavigate`), so we split Root into a thin outer shell
// that mounts the provider and an inner component that does the work.
export function Root() {
  return (
    <NotificationsProvider>
      <RootInner />
    </NotificationsProvider>
  );
}

// Theme management — toggles the `dark` class on <html>, persists the
// choice across sessions, and falls back to the OS preference on first
// load. Kept in this file (not a separate context) because it's a
// single boolean and the toggle lives next to sign-out.
function useTheme(): { dark: boolean; toggle: () => void } {
  const getInitial = (): boolean => {
    try {
      const stored = localStorage.getItem("regwatch.theme");
      if (stored === "dark") return true;
      if (stored === "light") return false;
    } catch {
      /* localStorage may be blocked in private mode */
    }
    return (
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-color-scheme: dark)")?.matches === true
    );
  };
  const [dark, setDark] = useState<boolean>(getInitial);
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", dark);
    try {
      localStorage.setItem("regwatch.theme", dark ? "dark" : "light");
    } catch {
      /* ignore */
    }
  }, [dark]);
  return { dark, toggle: () => setDark((d) => !d) };
}

function RootInner() {
  const navigate = useNavigate();
  const location = useLocation();
  const { unreadCount } = useNotifications();
  const { user, logout } = useAuth();
  const { dark, toggle: toggleTheme } = useTheme();
  const [activeView, setActiveView] = useState(() => {
    if (location.pathname === "/" || location.pathname.startsWith("/alerts")) return "inbox";
    if (location.pathname === "/archive") return "archive";
    if (location.pathname === "/regulatory-search") return "regulatory-search";
    if (location.pathname === "/areas-of-interest") return "areas-of-interest";
    if (location.pathname === "/sources") return "sources";
    if (location.pathname === "/costs") return "costs";
    return "inbox";
  });

  useEffect(() => {
    if (location.pathname === "/" || location.pathname.startsWith("/alerts")) setActiveView("inbox");
    else if (location.pathname === "/archive") setActiveView("archive");
    else if (location.pathname === "/regulatory-search") setActiveView("regulatory-search");
    else if (location.pathname === "/areas-of-interest") setActiveView("areas-of-interest");
    else if (location.pathname === "/sources") setActiveView("sources");
    else if (location.pathname === "/costs") setActiveView("costs");
  }, [location.pathname]);

  const handleNavigation = (view: string) => {
    setActiveView(view);
    if (view === "inbox") navigate("/alerts");
    else navigate(`/${view}`);
  };

  const getHeaderTitle = () => {
    if (location.pathname.startsWith("/alerts/")) return "Alert Details";
    if (activeView === "inbox") return "Inbox";
    if (activeView === "archive") return "Archive";
    if (activeView === "regulatory-search") return "Regulatory Search";
    if (activeView === "areas-of-interest") return "Areas of Interest";
    if (activeView === "sources") return "Sources";
    if (activeView === "costs") return "LLM Costs";
    return "Inbox";
  };

  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader>
          <div className="px-4 py-4">
            <div className="flex items-center gap-3">
              <img
                src={logoIcon}
                alt="MyTower"
                className="w-9 h-9 rounded-full shrink-0"
              />
              <div className="flex flex-col leading-tight min-w-0">
                <h3
                  className="text-sidebar-foreground font-bold"
                  style={{ fontSize: "var(--text-lg)" }}
                >
                  MyTower
                </h3>
                <span
                  className="text-accent font-medium"
                  style={{ fontSize: "var(--text-xs)" }}
                >
                  Beyond Borders
                </span>
              </div>
            </div>
            <p
              className="text-sidebar-foreground/60 mt-3"
              style={{ fontSize: "var(--text-xs)" }}
            >
              Global Trade Monitor
            </p>
          </div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    isActive={activeView === "inbox"}
                    onClick={() => handleNavigation("inbox")}
                  >
                    <Inbox />
                    <span>Inbox</span>
                    {unreadCount > 0 && (
                      <Badge className="ml-auto bg-accent text-accent-foreground tabular-nums">
                        {unreadCount > 999 ? "999+" : unreadCount}
                      </Badge>
                    )}
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    isActive={activeView === "archive"}
                    onClick={() => handleNavigation("archive")}
                  >
                    <Archive />
                    <span>Archive</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    isActive={activeView === "regulatory-search"}
                    onClick={() => handleNavigation("regulatory-search")}
                  >
                    <Search />
                    <span>Regulatory Search</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    isActive={activeView === "areas-of-interest"}
                    onClick={() => handleNavigation("areas-of-interest")}
                  >
                    <Target />
                    <span>Areas of Interest</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    isActive={activeView === "sources"}
                    onClick={() => handleNavigation("sources")}
                  >
                    <Globe />
                    <span>Sources</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    isActive={activeView === "costs"}
                    onClick={() => handleNavigation("costs")}
                  >
                    <Coins />
                    <span>LLM Costs</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <SidebarMenu>
            <SidebarMenuItem>
              <div className="px-3 pt-1 pb-2 min-w-0">
                <div
                  className="text-sidebar-foreground font-medium truncate"
                  style={{ fontSize: "var(--text-sm)" }}
                >
                  {user?.name || user?.email || "Signed in"}
                </div>
                {user?.email && user.name ? (
                  <div
                    className="text-sidebar-foreground/60 truncate"
                    style={{ fontSize: "var(--text-xs)" }}
                  >
                    {user.email}
                  </div>
                ) : null}
              </div>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton
                onClick={toggleTheme}
                title={dark ? "Switch to light mode" : "Switch to dark mode"}
              >
                {dark ? <Sun /> : <Moon />}
                <span>{dark ? "Light mode" : "Dark mode"}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton onClick={logout}>
                <LogOut />
                <span>Sign out</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        {/* Skip-link: invisible until keyboard-focused, then jumps the
            user past the sidebar nav directly to the page content.
            WCAG 2.4.1 (Bypass Blocks). */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-1.5 focus:text-primary-foreground"
        >
          Skip to main content
        </a>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-card px-4">
          <SidebarTrigger />
          <div className="flex items-center gap-2 flex-1">
            {/* Page <h1>. The visual size matches the previous <h2>
                (Tailwind / shadcn keep heading defaults equal); the
                semantic level is what assistive tech relies on. */}
            <h1 className="text-base font-semibold leading-tight">
              {getHeaderTitle()}
            </h1>
          </div>
          <SystemHealthIndicator />
        </header>
        <main
          id="main-content"
          className="flex-1 overflow-auto p-6"
          tabIndex={-1}
        >
          <Outlet />
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
