import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import {
  Alert as ApiAlert,
  AlertFeedback,
  listAlerts,
  updateAlert,
} from "@/api/alerts";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/app/components/ui/table";
import { Button } from "@/app/components/ui/button";
import { Badge } from "@/app/components/ui/badge";
import { Input } from "@/app/components/ui/input";
import {
  ThumbsUp,
  ThumbsDown,
  AlertTriangle,
  Eye,
  EyeOff,
  Search,
  Pin,
  ArchiveRestore,
  Archive as ArchiveIcon,
} from "lucide-react";
import { IN, CN, EU, US } from "country-flag-icons/react/3x2";
import { useNotifications } from "@/app/notifications";

type Alert = ApiAlert;

// Dev-only fallback used when the API isn't reachable.
const mockAlerts: Alert[] = [
  { id: "ALT-001", title: "New tariff rates for semiconductor imports effective March 2026", country: "India", authority: "Directorate General of Foreign Trade (DGFT)", regulationType: "Tariff & Duties", publicationDate: "2026-01-15", affectedProducts: ["HS 854140", "HS 850440"], relevanceScore: 92, status: "read", userFeedback: "relevant", tradeLane: "*->IN" },
  { id: "ALT-002", title: "Updated import licensing requirements for electrical machinery", country: "China", authority: "Ministry of Commerce (MOFCOM)", regulationType: "Licensing & Permits", publicationDate: "2026-01-18", affectedProducts: ["HS 850440", "HS 851770"], relevanceScore: 87, status: "read", userFeedback: "relevant", tradeLane: "*->CN" },
  { id: "ALT-003", title: "Conformity assessment changes for consumer electronics", country: "EU", authority: "European Commission", regulationType: "Labeling & Conformity", publicationDate: "2026-01-20", affectedProducts: ["HS 854140", "HS 851762"], relevanceScore: 78, status: "read", tradeLane: "*->EU" },
  { id: "ALT-004", title: "Export restriction on dual-use semiconductor equipment", country: "United States", authority: "Bureau of Industry and Security (BIS)", regulationType: "Export Restrictions", publicationDate: "2026-01-12", affectedProducts: ["HS 854140"], relevanceScore: 95, status: "read", userFeedback: "relevant", tradeLane: "US->*" },
  { id: "ALT-005", title: "Revised customs clearance procedures for electronic goods", country: "India", authority: "Central Board of Indirect Taxes and Customs (CBIC)", regulationType: "Import/Export Procedures", publicationDate: "2026-01-10", affectedProducts: ["HS 854140", "HS 850440", "HS 851770"], relevanceScore: 65, status: "read", tradeLane: "*->IN" },
  { id: "ALT-006", title: "Anti-dumping duty investigation on lithium batteries", country: "EU", authority: "European Commission - DG Trade", regulationType: "Anti-dumping Measures", publicationDate: "2026-01-08", affectedProducts: ["HS 850760", "HS 850720"], relevanceScore: 88, status: "read", userFeedback: "relevant", tradeLane: "CN->EU" },
  { id: "ALT-007", title: "New environmental compliance standards for electronic waste", country: "China", authority: "Ministry of Ecology and Environment", regulationType: "Environmental Standards", publicationDate: "2026-01-05", affectedProducts: ["HS 854140", "HS 851770", "HS 850440"], relevanceScore: 72, status: "read", tradeLane: "*->CN" },
  { id: "ALT-008", title: "Updated certification requirements for wireless devices", country: "United States", authority: "Federal Communications Commission (FCC)", regulationType: "Labeling & Conformity", publicationDate: "2026-01-03", affectedProducts: ["HS 851762", "HS 851770"], relevanceScore: 81, status: "read", userFeedback: "partially_relevant", tradeLane: "*->US" },
  { id: "ALT-009", title: "Import quota changes for steel products", country: "India", authority: "Ministry of Steel", regulationType: "Quotas & Restrictions", publicationDate: "2025-12-28", affectedProducts: ["HS 720710", "HS 720890"], relevanceScore: 45, status: "read", tradeLane: "*->IN" },
  { id: "ALT-010", title: "Origin marking requirements for consumer goods", country: "United States", authority: "U.S. Customs and Border Protection", regulationType: "Labeling & Conformity", publicationDate: "2025-12-22", affectedProducts: ["HS 854140", "HS 850440"], relevanceScore: 68, status: "read", tradeLane: "CN->US" },
  { id: "ALT-011", title: "Chemical safety regulations update for batteries", country: "EU", authority: "European Chemicals Agency (ECHA)", regulationType: "Safety Standards", publicationDate: "2025-12-20", affectedProducts: ["HS 850760", "HS 850720"], relevanceScore: 76, status: "read", userFeedback: "relevant", tradeLane: "*->EU" },
  { id: "ALT-012", title: "Cybersecurity requirements for IoT devices", country: "EU", authority: "European Union Agency for Cybersecurity (ENISA)", regulationType: "Safety Standards", publicationDate: "2025-12-15", affectedProducts: ["HS 851762", "HS 851770"], relevanceScore: 84, status: "read", tradeLane: "*->EU" },
  { id: "ALT-013", title: "Trade remedies on solar panel imports extended", country: "United States", authority: "U.S. International Trade Commission", regulationType: "Anti-dumping Measures", publicationDate: "2025-12-10", affectedProducts: ["HS 854140"], relevanceScore: 62, status: "read", tradeLane: "CN->US" },
  { id: "ALT-014", title: "Prohibited substances list update for electronics", country: "China", authority: "State Administration for Market Regulation", regulationType: "Safety Standards", publicationDate: "2025-12-08", affectedProducts: ["HS 854140", "HS 850440", "HS 851770"], relevanceScore: 79, status: "read", userFeedback: "relevant", tradeLane: "*->CN" },
  { id: "ALT-015", title: "Packaging and recycling requirements for electronics", country: "EU", authority: "European Parliament and Council", regulationType: "Environmental Standards", publicationDate: "2025-12-05", affectedProducts: ["HS 854140", "HS 851762"], relevanceScore: 70, status: "read", tradeLane: "*->EU" },
  { id: "ALT-016", title: "Import ban on certain electronic components", country: "India", authority: "Ministry of Electronics and IT", regulationType: "Import Restrictions", publicationDate: "2025-12-01", affectedProducts: ["HS 854140"], relevanceScore: 91, status: "read", userFeedback: "relevant", tradeLane: "*->IN" },
  { id: "ALT-017", title: "Energy efficiency labeling requirements update", country: "China", authority: "National Development and Reform Commission", regulationType: "Labeling & Conformity", publicationDate: "2025-11-28", affectedProducts: ["HS 850440", "HS 851770"], relevanceScore: 58, status: "read", tradeLane: "*->CN" },
  { id: "ALT-018", title: "Product safety recall procedures modernization", country: "United States", authority: "Consumer Product Safety Commission", regulationType: "Safety Standards", publicationDate: "2025-11-25", affectedProducts: ["HS 854140", "HS 851762"], relevanceScore: 73, status: "read", tradeLane: "*->US" },
  { id: "ALT-019", title: "Digital trade facilitation platform launch", country: "India", authority: "Directorate General of Foreign Trade (DGFT)", regulationType: "Import/Export Procedures", publicationDate: "2025-11-20", affectedProducts: ["HS 854140", "HS 850440", "HS 851770"], relevanceScore: 55, status: "read", tradeLane: "IN->*" },
  { id: "ALT-020", title: "Intellectual property enforcement at borders strengthened", country: "EU", authority: "European Commission - DG Taxation", regulationType: "Import/Export Procedures", publicationDate: "2025-11-18", affectedProducts: ["HS 854140", "HS 851762"], relevanceScore: 67, status: "read", tradeLane: "*->EU" },
];

export function ArchiveView() {
  const navigate = useNavigate();
  const { refreshUnread } = useNotifications();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [globalSearchQuery, setGlobalSearchQuery] = useState("");

  const [titleFilter, setTitleFilter] = useState("");
  const [countryFilter, setCountryFilter] = useState("");
  const [tradeLaneFilter, setTradeLaneFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [dateFilter, setDateFilter] = useState("");
  const [productsFilter, setProductsFilter] = useState("");

  // Archive shows ONLY status="archived" alerts. No fallback to "read"
  // (that was masking the bug where there's no path to set
  // status=archived from the inbox — there is one now: the Archive
  // button on each row in AlertsView).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listAlerts({ status: "archived", limit: 200 })
      .then((rows) => {
        if (cancelled) return;
        setAlerts(rows);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        console.warn("Archive API unreachable:", err.message);
        // Don't fall back to mock data here — it'd misrepresent state.
        setAlerts([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRestore = (alertId: string) => {
    // Move the alert back to "new" so it's visible in the inbox again.
    setAlerts((prev) => prev.filter((a) => a.id !== alertId));
    updateAlert(alertId, { status: "new" })
      .then(() => void refreshUnread())
      .catch((err) => console.warn("restore PATCH failed:", err));
  };

  const handleFeedback = (alertId: string, feedback: AlertFeedback) => {
    setAlerts((prev) =>
      prev.map((alert) =>
        alert.id === alertId ? { ...alert, userFeedback: feedback } : alert,
      ),
    );
    updateAlert(alertId, { userFeedback: feedback }).catch((err) =>
      console.warn("feedback PATCH failed:", err),
    );
  };

  const toggleSeen = (alertId: string) => {
    let nextStatus: "new" | "read" = "read";
    setAlerts((prev) =>
      prev.map((alert) => {
        if (alert.id !== alertId) return alert;
        nextStatus = alert.status === "new" ? "read" : "new";
        return { ...alert, status: nextStatus };
      }),
    );
    updateAlert(alertId, { status: nextStatus }).catch((err) =>
      console.warn("status PATCH failed:", err),
    );
  };

  const togglePin = (alertId: string) => {
    let nextPinned = false;
    setAlerts((prev) =>
      prev.map((alert) => {
        if (alert.id !== alertId) return alert;
        nextPinned = !alert.pinned;
        return { ...alert, pinned: nextPinned };
      }),
    );
    updateAlert(alertId, { pinned: nextPinned }).catch((err) =>
      console.warn("pin PATCH failed:", err),
    );
  };

  const getRelevanceColor = (score: number) => {
    if (score >= 80) return "bg-accent text-accent-foreground";
    if (score >= 60) return "bg-primary text-primary-foreground";
    return "bg-muted text-muted-foreground";
  };

  const getCountryFlag = (country: string) => {
    const flagMap: { [key: string]: React.ReactNode } = {
      India: <span className="inline-flex"><IN className="size-6" /></span>,
      China: <span className="inline-flex"><CN className="size-6" /></span>,
      EU: <span className="inline-flex"><EU className="size-6" /></span>,
      "United States": <span className="inline-flex"><US className="size-6" /></span>,
    };
    return flagMap[country] || "🌐";
  };

  const filteredAlerts = alerts.filter((alert) => {
    const globalQuery = globalSearchQuery.toLowerCase();
    const globalMatch =
      globalSearchQuery === "" ||
      alert.title.toLowerCase().includes(globalQuery) ||
      alert.country.toLowerCase().includes(globalQuery) ||
      alert.authority.toLowerCase().includes(globalQuery) ||
      alert.regulationType.toLowerCase().includes(globalQuery) ||
      alert.affectedProducts.some((product) =>
        product.toLowerCase().includes(globalQuery),
      ) ||
      alert.id.toLowerCase().includes(globalQuery);

    const titleMatch =
      titleFilter === "" ||
      alert.title.toLowerCase().includes(titleFilter.toLowerCase());
    const countryMatch =
      countryFilter === "" ||
      alert.country.toLowerCase().includes(countryFilter.toLowerCase());
    const tradeLaneMatch =
      tradeLaneFilter === "" ||
      alert.tradeLane.toLowerCase().includes(tradeLaneFilter.toLowerCase());
    const typeMatch =
      typeFilter === "" ||
      alert.regulationType.toLowerCase().includes(typeFilter.toLowerCase());
    const dateMatch = dateFilter === "" || alert.publicationDate.includes(dateFilter);
    const productsMatch =
      productsFilter === "" ||
      alert.affectedProducts.some((product) =>
        product.toLowerCase().includes(productsFilter.toLowerCase()),
      );

    return (
      globalMatch &&
      titleMatch &&
      countryMatch &&
      tradeLaneMatch &&
      typeMatch &&
      dateMatch &&
      productsMatch
    );
  });

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <p className="text-muted-foreground">Loading archive…</p>
      </div>
    );
  }

  // Truly-empty state: no archived alerts and no search filter active.
  // Earlier the page lied here by showing read alerts as a "fallback";
  // we no longer do that — say so honestly.
  if (alerts.length === 0 && globalSearchQuery === "") {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh]">
        <div className="text-center space-y-4">
          <div className="flex items-center justify-center mb-4">
            <div className="rounded-full bg-muted p-6">
              <ArchiveIcon className="size-12 text-muted-foreground" />
            </div>
          </div>
          <h2 className="text-2xl">Nothing archived yet</h2>
          <p className="text-muted-foreground">
            Use the Archive button on each alert in the inbox to dismiss
            it once you've reviewed it.
          </p>
          <Button
            variant="link"
            onClick={() => navigate("/alerts")}
            className="text-primary"
          >
            ← Go to inbox
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-muted-foreground">
            Search and review archived regulatory alerts
          </p>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="text"
            placeholder="Search all alerts..."
            value={globalSearchQuery}
            onChange={(e) => setGlobalSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        {globalSearchQuery && (
          <Button variant="ghost" onClick={() => setGlobalSearchQuery("")}>
            Clear
          </Button>
        )}
      </div>

      <div className="rounded-md border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead style={{ width: "40px" }}></TableHead>
              <TableHead style={{ width: "40px" }}>Status</TableHead>
              <TableHead>Alert</TableHead>
              <TableHead style={{ width: "120px" }}>Country</TableHead>
              <TableHead style={{ width: "120px" }}>Trade Lane</TableHead>
              <TableHead style={{ width: "150px" }}>Type</TableHead>
              <TableHead style={{ width: "120px" }}>Date</TableHead>
              <TableHead>Products</TableHead>
              <TableHead style={{ width: "80px" }}>Relevance</TableHead>
              <TableHead style={{ width: "200px" }}>Feedback</TableHead>
            </TableRow>
            <TableRow className="hover:bg-transparent">
              <TableHead></TableHead>
              <TableHead></TableHead>
              <TableHead>
                <Input
                  type="text"
                  placeholder="Filter..."
                  value={titleFilter}
                  onChange={(e) => setTitleFilter(e.target.value)}
                  className="h-8"
                  style={{ fontSize: "var(--text-xs)" }}
                />
              </TableHead>
              <TableHead>
                <Input
                  type="text"
                  placeholder="Filter..."
                  value={countryFilter}
                  onChange={(e) => setCountryFilter(e.target.value)}
                  className="h-8"
                  style={{ fontSize: "var(--text-xs)" }}
                />
              </TableHead>
              <TableHead>
                <Input
                  type="text"
                  placeholder="Filter..."
                  value={tradeLaneFilter}
                  onChange={(e) => setTradeLaneFilter(e.target.value)}
                  className="h-8"
                  style={{ fontSize: "var(--text-xs)" }}
                />
              </TableHead>
              <TableHead>
                <Input
                  type="text"
                  placeholder="Filter..."
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}
                  className="h-8"
                  style={{ fontSize: "var(--text-xs)" }}
                />
              </TableHead>
              <TableHead>
                <Input
                  type="text"
                  placeholder="YYYY-MM-DD"
                  value={dateFilter}
                  onChange={(e) => setDateFilter(e.target.value)}
                  className="h-8"
                  style={{ fontSize: "var(--text-xs)" }}
                />
              </TableHead>
              <TableHead>
                <Input
                  type="text"
                  placeholder="HS code..."
                  value={productsFilter}
                  onChange={(e) => setProductsFilter(e.target.value)}
                  className="h-8"
                  style={{ fontSize: "var(--text-xs)" }}
                />
              </TableHead>
              <TableHead></TableHead>
              <TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredAlerts.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} className="h-24 text-center">
                  <div className="flex flex-col items-center gap-2">
                    <Search className="size-8 text-muted-foreground" />
                    <p className="text-muted-foreground">
                      No alerts found matching your filters
                    </p>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              filteredAlerts.map((alert) => (
                <TableRow key={alert.id}>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => togglePin(alert.id)}
                      title={alert.pinned ? "Unpin alert" : "Pin to top"}
                      className={
                        alert.pinned ? "text-primary" : "text-muted-foreground"
                      }
                    >
                      <Pin
                        className={`size-4 ${alert.pinned ? "fill-current" : ""}`}
                      />
                    </Button>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-0.5">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => toggleSeen(alert.id)}
                        title={
                          alert.status === "new" ? "Mark as seen" : "Mark as new"
                        }
                      >
                        {alert.status === "new" ? (
                          <EyeOff className="size-4" />
                        ) : (
                          <Eye className="size-4" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleRestore(alert.id)}
                        title="Restore — move back to inbox"
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <ArchiveRestore className="size-4" />
                      </Button>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="max-w-md">
                      <div className="flex items-start gap-2">
                        {alert.status === "new" && (
                          <Badge variant="default" className="shrink-0">
                            New
                          </Badge>
                        )}
                        <div>
                          <p
                            onClick={() => navigate(`/alerts/${alert.id}`)}
                            className="cursor-pointer hover:text-primary hover:underline"
                            style={{
                              fontWeight:
                                alert.status === "new"
                                  ? "var(--font-weight-medium)"
                                  : "var(--font-weight-normal)",
                            }}
                          >
                            {alert.title}
                          </p>
                          <p
                            className="text-muted-foreground"
                            style={{
                              fontSize: "var(--text-xs)",
                              marginTop: "4px",
                            }}
                          >
                            {alert.authority}
                          </p>
                        </div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {getCountryFlag(alert.country)}
                      <span>{alert.country}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{alert.tradeLane}</Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{alert.regulationType}</Badge>
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {(() => {
                      const d = new Date(alert.publicationDate);
                      if (Number.isNaN(d.getTime())) return "—";
                      return (
                        <>
                          <div>
                            {d.toLocaleDateString("en-US", {
                              month: "short",
                              day: "numeric",
                              year: "numeric",
                            })}
                          </div>
                          <div
                            style={{ fontSize: "var(--text-xs)" }}
                            className="text-muted-foreground"
                          >
                            {d.toLocaleTimeString("en-US", {
                              hour: "2-digit",
                              minute: "2-digit",
                              hour12: false,
                            })}
                          </div>
                        </>
                      );
                    })()}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {alert.affectedProducts.slice(0, 2).map((product, idx) => (
                        <Badge
                          key={idx}
                          variant="secondary"
                          className="bg-muted text-foreground"
                        >
                          {product}
                        </Badge>
                      ))}
                      {alert.affectedProducts.length > 2 && (
                        <Badge
                          variant="secondary"
                          className="bg-muted text-foreground"
                        >
                          +{alert.affectedProducts.length - 2}
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge className={getRelevanceColor(alert.relevanceScore)}>
                      {alert.relevanceScore}%
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button
                        variant={
                          alert.userFeedback === "relevant" ? "default" : "outline"
                        }
                        size="sm"
                        onClick={() => handleFeedback(alert.id, "relevant")}
                        title="Relevant"
                      >
                        <ThumbsUp className="size-4" />
                      </Button>
                      <Button
                        variant={
                          alert.userFeedback === "partially_relevant"
                            ? "default"
                            : "outline"
                        }
                        size="sm"
                        onClick={() =>
                          handleFeedback(alert.id, "partially_relevant")
                        }
                        title="Partially relevant"
                      >
                        <AlertTriangle className="size-4" />
                      </Button>
                      <Button
                        variant={
                          alert.userFeedback === "not_relevant"
                            ? "destructive"
                            : "outline"
                        }
                        size="sm"
                        onClick={() => handleFeedback(alert.id, "not_relevant")}
                        title="Not relevant"
                      >
                        <ThumbsDown className="size-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
