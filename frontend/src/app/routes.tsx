import { createHashRouter } from "react-router";
import { Root } from "./root";
import { AlertsView } from "./components/alerts-view";
import { AlertDetail } from "./components/alert-detail";
import { AreasOfInterestView } from "./components/areas-of-interest-view";
import { SourcesView } from "./components/sources-view";
import { ArchiveView } from "./components/archive-view";
import { RegulatorySearchView } from "./components/regulatory-search-view";
import { CostReportView } from "./components/cost-report-view";

export const router = createHashRouter([
  {
    path: "/",
    Component: Root,
    children: [
      { index: true, Component: AlertsView },
      { path: "alerts", Component: AlertsView },
      { path: "alerts/:id", Component: AlertDetail },
      { path: "archive", Component: ArchiveView },
      { path: "regulatory-search", Component: RegulatorySearchView },
      { path: "areas-of-interest", Component: AreasOfInterestView },
      { path: "sources", Component: SourcesView },
      { path: "costs", Component: CostReportView },
    ],
  },
]);
