import { useState, useEffect } from "react";
import { useNavigate, useLocation, Outlet } from "react-router";
import {
  Sidebar,
  SidebarContent,
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
} from "lucide-react";
import { Badge } from "@/app/components/ui/badge";
import {
  NotificationsProvider,
  useNotifications,
} from "@/app/notifications";
import { SystemHealthIndicator } from "@/app/components/system-health";
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

function RootInner() {
  const navigate = useNavigate();
  const location = useLocation();
  const { unreadCount } = useNotifications();
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
      </Sidebar>
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-card px-4">
          <SidebarTrigger />
          <div className="flex items-center gap-2 flex-1">
            <h2>{getHeaderTitle()}</h2>
          </div>
          <SystemHealthIndicator />
        </header>
        <div className="flex-1 overflow-auto p-6">
          <Outlet />
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
