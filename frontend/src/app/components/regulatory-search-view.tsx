import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { Alert as ApiAlert, listAlerts } from "@/api/alerts";
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
import { Search, FileSearch } from "lucide-react";
import { IN, CN, EU, US } from "country-flag-icons/react/3x2";

type Alert = ApiAlert;

// Differs from AlertsView (inbox) in two ways:
//   1. Searches across every alert regardless of status — including read,
//      archived, dismissed.
//   2. Empty query shows an empty state, not a flood of rows. The page
//      is for *finding* a known regulation, not browsing.
export function RegulatorySearchView() {
  const navigate = useNavigate();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    // No status filter → backend returns every alert. The frontend
    // does case-insensitive substring matching across the indexed
    // fields below.
    listAlerts({ limit: 200 })
      .then((rows) => {
        if (!cancelled) setAlerts(rows);
      })
      .catch((err: Error) => {
        console.warn("Search load failed:", err.message);
        if (!cancelled) setAlerts([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const getRelevanceColor = (score: number) => {
    if (score >= 80) return "bg-accent text-accent-foreground";
    if (score >= 60) return "bg-primary text-primary-foreground";
    return "bg-muted text-muted-foreground";
  };

  const getCountryFlag = (country: string) => {
    const flagMap: { [key: string]: React.ReactNode } = {
      India: <IN className="size-5" />,
      China: <CN className="size-5" />,
      EU: <EU className="size-5" />,
      "United States": <US className="size-5" />,
    };
    return flagMap[country] || <span className="text-base">🌐</span>;
  };

  const query = searchQuery.trim().toLowerCase();
  const results =
    query === ""
      ? []
      : alerts.filter((a) => {
          return (
            a.title.toLowerCase().includes(query) ||
            a.country.toLowerCase().includes(query) ||
            a.authority.toLowerCase().includes(query) ||
            a.regulationType.toLowerCase().includes(query) ||
            a.tradeLane.toLowerCase().includes(query) ||
            a.affectedProducts.some((p) => p.toLowerCase().includes(query)) ||
            a.id.toLowerCase().includes(query)
          );
        });

  return (
    <div className="space-y-6">
      <div>
        <p className="text-muted-foreground">
          Search across every regulatory alert — new, read, and archived.
        </p>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          autoFocus
          type="text"
          placeholder="Search by title, country, authority, regulation type, HS code, or trade lane..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-9 h-11"
        />
      </div>

      {loading ? (
        <p className="text-muted-foreground">Indexing alerts…</p>
      ) : query === "" ? (
        <div className="flex flex-col items-center justify-center min-h-[40vh] text-center space-y-3">
          <div className="rounded-full bg-muted p-5">
            <FileSearch className="size-10 text-muted-foreground" />
          </div>
          <div>
            <h3>Find a regulation</h3>
            <p
              className="text-muted-foreground mt-1"
              style={{ fontSize: "var(--text-sm)" }}
            >
              {alerts.length.toLocaleString()} alerts indexed. Type above to
              search by keyword, country, authority, HS code, or trade lane.
            </p>
          </div>
        </div>
      ) : results.length === 0 ? (
        <div className="flex flex-col items-center justify-center min-h-[40vh] text-center">
          <Search className="size-8 text-muted-foreground mb-3" />
          <p className="text-muted-foreground">
            No alerts found matching "{searchQuery}"
          </p>
        </div>
      ) : (
        <>
          <p
            className="text-muted-foreground"
            style={{ fontSize: "var(--text-sm)" }}
          >
            {results.length.toLocaleString()} result
            {results.length === 1 ? "" : "s"} for "{searchQuery}"
          </p>
          <div className="rounded-md border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Alert</TableHead>
                  <TableHead style={{ width: "120px" }}>Country</TableHead>
                  <TableHead style={{ width: "120px" }}>Trade Lane</TableHead>
                  <TableHead style={{ width: "150px" }}>Type</TableHead>
                  <TableHead style={{ width: "120px" }}>Date</TableHead>
                  <TableHead style={{ width: "100px" }}>Status</TableHead>
                  <TableHead style={{ width: "80px" }}>Relevance</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((alert) => (
                  <TableRow
                    key={alert.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/alerts/${alert.id}`)}
                  >
                    <TableCell>
                      <div className="max-w-md">
                        <p
                          className="hover:text-primary hover:underline"
                          style={{ fontWeight: "var(--font-weight-medium)" }}
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
                    <TableCell className="text-muted-foreground">
                      {alert.publicationDate
                        ? new Date(alert.publicationDate).toLocaleDateString(
                            "en-US",
                            {
                              month: "short",
                              day: "numeric",
                              year: "numeric",
                            },
                          )
                        : "—"}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className="capitalize text-muted-foreground"
                      >
                        {alert.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge className={getRelevanceColor(alert.relevanceScore)}>
                        {alert.relevanceScore}%
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </div>
  );
}
