import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router";
import { Bell, Check, X } from "lucide-react";
import { Alert, listAlerts } from "@/api/alerts";

// ─────────────────────────────────────────────────────────────────────
// App-wide notifications + unread-alert count.
//
// Why this exists:
//   - The "Inbox" badge in the sidebar needs a real unread count, not a
//     hardcoded "16".
//   - When a crawl finishes with new alerts we want a toast pop on
//     whatever page the user is on, with a one-click jump to the inbox.
//
// Provider responsibilities:
//   - Fetch unread (status="new") count on mount, every 60s, and on tab
//     focus. That cadence is enough for the badge to feel live without
//     hammering the API.
//   - Expose a `notify(...)` to fire ad-hoc toasts.
//   - Render the toast stack at fixed bottom-right.
// ─────────────────────────────────────────────────────────────────────

export type ToastVariant = "info" | "success" | "error";

export interface Toast {
  id: string;
  message: string;
  description?: string;
  variant: ToastVariant;
  href?: string;
}

/**
 * Lite shape of an unread alert — just enough to render a toast and
 * deep-link to the detail page.
 */
export type UnreadAlert = Pick<
  Alert,
  "id" | "title" | "country" | "authority" | "relevanceScore"
>;

interface NotificationsContextValue {
  /** Real-time count of alerts with status === "new". */
  unreadCount: number;
  /**
   * Latest snapshot of unread alerts (lite shape). Lets callers compute
   * which alerts are *new since* a particular point in time by diffing
   * IDs.
   */
  unreadAlerts: UnreadAlert[];
  /**
   * Force a re-fetch — call after marking alerts read or after a crawl.
   * Returns the new alerts (lite shape) on success, null on failure.
   */
  refreshUnread: () => Promise<UnreadAlert[] | null>;
  /** Pop a toast. Returns the toast id so callers can dismiss programmatically. */
  notify: (
    message: string,
    opts?: {
      description?: string;
      variant?: ToastVariant;
      /** When set, the toast becomes a clickable link to this hash route. */
      href?: string;
      /** ms before auto-dismiss. Default 8000. Pass 0 to keep until dismissed. */
      durationMs?: number;
    },
  ) => string;
  dismissToast: (id: string) => void;
}

const NotificationsContext = createContext<NotificationsContextValue | null>(
  null,
);

export function useNotifications(): NotificationsContextValue {
  const ctx = useContext(NotificationsContext);
  if (!ctx) {
    throw new Error(
      "useNotifications must be used inside <NotificationsProvider>",
    );
  }
  return ctx;
}

const REFRESH_INTERVAL_MS = 60_000;

export function NotificationsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [unreadCount, setUnreadCount] = useState(0);
  const [unreadAlerts, setUnreadAlerts] = useState<UnreadAlert[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  // Track timeout ids so we can cancel auto-dismiss when the user
  // dismisses manually (avoids state updates after unmount).
  const dismissTimersRef = useRef<Record<string, number>>({});

  const refreshUnread = useCallback(
    async (): Promise<UnreadAlert[] | null> => {
      try {
        // limit=200 matches the inbox view — same upper bound, same
        // shape of data. If you get more than 200 new alerts you've got
        // bigger problems than badge accuracy.
        const rows = await listAlerts({ status: "new", limit: 200 });
        const lite: UnreadAlert[] = rows.map((r) => ({
          id: r.id,
          title: r.title,
          country: r.country,
          authority: r.authority,
          relevanceScore: r.relevanceScore,
        }));
        setUnreadCount(rows.length);
        setUnreadAlerts(lite);
        return lite;
      } catch {
        // Silent — failing silently keeps the badge as the last-known
        // value rather than blanking on transient API hiccups.
        return null;
      }
    },
    [],
  );

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    if (dismissTimersRef.current[id] !== undefined) {
      window.clearTimeout(dismissTimersRef.current[id]);
      delete dismissTimersRef.current[id];
    }
  }, []);

  const notify = useCallback<NotificationsContextValue["notify"]>(
    (message, opts = {}) => {
      const id = Math.random().toString(36).slice(2);
      const t: Toast = {
        id,
        message,
        description: opts.description,
        variant: opts.variant ?? "info",
        href: opts.href,
      };
      setToasts((prev) => [...prev, t]);
      const ms = opts.durationMs ?? 8000;
      if (ms > 0) {
        dismissTimersRef.current[id] = window.setTimeout(() => {
          dismissToast(id);
        }, ms);
      }
      return id;
    },
    [dismissToast],
  );

  // Initial fetch + periodic refresh + tab-focus refresh.
  useEffect(() => {
    void refreshUnread();
    const id = window.setInterval(() => void refreshUnread(), REFRESH_INTERVAL_MS);
    const onFocus = () => void refreshUnread();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [refreshUnread]);

  // Cancel any in-flight auto-dismiss timers on unmount.
  useEffect(() => {
    return () => {
      Object.values(dismissTimersRef.current).forEach((id) =>
        window.clearTimeout(id),
      );
    };
  }, []);

  return (
    <NotificationsContext.Provider
      value={{
        unreadCount,
        unreadAlerts,
        refreshUnread,
        notify,
        dismissToast,
      }}
    >
      {children}
      <ToastStack toasts={toasts} dismiss={dismissToast} />
    </NotificationsContext.Provider>
  );
}

// ── Toast UI ────────────────────────────────────────────────────────

function ToastStack({
  toasts,
  dismiss,
}: {
  toasts: Toast[];
  dismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div
      role="region"
      aria-label="Notifications"
      className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 w-96 max-w-[calc(100vw-2rem)] pointer-events-none"
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} dismiss={dismiss} />
      ))}
    </div>
  );
}

function ToastItem({
  toast,
  dismiss,
}: {
  toast: Toast;
  dismiss: (id: string) => void;
}) {
  const navigate = useNavigate();
  const Icon =
    toast.variant === "success" ? Check : toast.variant === "error" ? X : Bell;
  const tint =
    toast.variant === "success"
      ? "border-accent/40 [&_.toast-icon]:text-accent"
      : toast.variant === "error"
        ? "border-destructive/40 [&_.toast-icon]:text-destructive"
        : "border-border [&_.toast-icon]:text-primary";

  const handleClick = () => {
    if (toast.href) {
      navigate(toast.href);
      dismiss(toast.id);
    }
  };

  return (
    <div
      className={`pointer-events-auto rounded-md border bg-card shadow-lg animate-in slide-in-from-bottom-2 fade-in-0 duration-300 ${tint}`}
    >
      <div className="px-4 py-3 flex items-start gap-3">
        <Icon className="toast-icon size-5 shrink-0 mt-0.5" />
        <div
          className={`flex-1 min-w-0 ${toast.href ? "cursor-pointer" : ""}`}
          onClick={handleClick}
          role={toast.href ? "button" : undefined}
        >
          <p
            className="truncate"
            style={{ fontWeight: "var(--font-weight-medium)" }}
          >
            {toast.message}
          </p>
          {toast.description && (
            <p
              className="text-muted-foreground"
              style={{ fontSize: "var(--text-xs)", marginTop: "2px" }}
            >
              {toast.description}
            </p>
          )}
          {toast.href && (
            <p
              className="text-primary mt-1"
              style={{ fontSize: "var(--text-xs)" }}
            >
              Click to view →
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => dismiss(toast.id)}
          aria-label="Dismiss"
          className="text-muted-foreground hover:text-foreground shrink-0"
        >
          <X className="size-4" />
        </button>
      </div>
    </div>
  );
}
