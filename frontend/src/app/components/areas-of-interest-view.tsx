import React, { useEffect, useState } from "react";
import { getAreas, saveAreas } from "@/api/areas";

// No auth in the app yet — every user shares one profile. Override with
// VITE_USER_EMAIL if you want to test multi-user locally.
const CURRENT_USER_EMAIL =
  (typeof import.meta !== "undefined" &&
    (import.meta as any).env?.VITE_USER_EMAIL) ||
  "current.user@regwatch.app";

// Walk an HS tree marking nodes as selected when their code is in `codes`.
function applySelections(nodes: HSNode[], codes: Set<string>): HSNode[] {
  return nodes.map((n) => ({
    ...n,
    selected: codes.has(n.code),
    expanded: n.expanded,
    children: n.children ? applySelections(n.children, codes) : undefined,
  }));
}

// Walk the tree and collect every selected node's raw code (e.g. "854140").
function collectSelectedCodes(nodes: HSNode[]): string[] {
  const out: string[] = [];
  const walk = (ns: HSNode[]) => {
    for (const n of ns) {
      if (n.selected) out.push(n.code);
      if (n.children) walk(n.children);
    }
  };
  walk(nodes);
  return out;
}
import { Button } from "@/app/components/ui/button";
import { Badge } from "@/app/components/ui/badge";
import { Input } from "@/app/components/ui/input";
import { Checkbox } from "@/app/components/ui/checkbox";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/app/components/ui/tabs";
import { ScrollArea } from "@/app/components/ui/scroll-area";
import {
  Search,
  ChevronRight,
  ChevronDown,
  X,
  Package,
  Globe,
  Tag,
} from "lucide-react";
import {
  IN,
  CN,
  EU,
  US,
  JP,
  KR,
  SG,
  MY,
  TH,
  VN,
  ID,
  MX,
  CA,
  AE,
  SA,
} from "country-flag-icons/react/3x2";

interface HSNode {
  code: string;
  description: string;
  children?: HSNode[];
  selected?: boolean;
  expanded?: boolean;
  partial?: boolean;
}

interface Country {
  code: string;
  name: string;
  flag: React.ReactNode;
}

interface RegionGroup {
  name: string;
  countries: string[];
}

const hsTreeData: HSNode[] = [
  {
    code: "84",
    description: "Nuclear reactors, boilers, machinery",
    children: [
      {
        code: "8471",
        description: "Automatic data processing machines",
        children: [
          { code: "847130", description: "Portable automatic data processing machines" },
          { code: "847141", description: "Comprising in the same housing at least a CPU and input/output unit" },
        ],
      },
    ],
  },
  {
    code: "85",
    description: "Electrical machinery and equipment",
    children: [
      {
        code: "8504",
        description: "Electrical transformers, static converters",
        children: [
          { code: "850440", description: "Static converters" },
          { code: "850450", description: "Other inductors" },
        ],
      },
      {
        code: "8517",
        description: "Telephone sets and communication apparatus",
        children: [
          { code: "851762", description: "Machines for reception, conversion and transmission" },
          { code: "851770", description: "Parts" },
        ],
      },
      {
        code: "8541",
        description: "Semiconductor devices; light-emitting diodes",
        children: [
          { code: "854140", description: "Photosensitive semiconductor devices, including photovoltaic cells" },
          { code: "854150", description: "Other semiconductor devices" },
        ],
      },
      {
        code: "8507",
        description: "Electric accumulators",
        children: [
          { code: "850760", description: "Lithium-ion batteries" },
          { code: "850720", description: "Other lead-acid accumulators" },
        ],
      },
    ],
  },
  {
    code: "72",
    description: "Iron and steel",
    children: [
      {
        code: "7207",
        description: "Semi-finished products of iron or non-alloy steel",
        children: [
          { code: "720710", description: "Containing by weight less than 0.25% of carbon" },
        ],
      },
      {
        code: "7208",
        description: "Flat-rolled products of iron or non-alloy steel",
        children: [{ code: "720890", description: "Other" }],
      },
    ],
  },
];

const countries: Country[] = [
  { code: "US", name: "United States", flag: <US className="size-5" /> },
  { code: "CN", name: "China", flag: <CN className="size-5" /> },
  { code: "IN", name: "India", flag: <IN className="size-5" /> },
  { code: "JP", name: "Japan", flag: <JP className="size-5" /> },
  { code: "KR", name: "South Korea", flag: <KR className="size-5" /> },
  { code: "EU", name: "European Union", flag: <EU className="size-5" /> },
  { code: "SG", name: "Singapore", flag: <SG className="size-5" /> },
  { code: "MY", name: "Malaysia", flag: <MY className="size-5" /> },
  { code: "TH", name: "Thailand", flag: <TH className="size-5" /> },
  { code: "VN", name: "Vietnam", flag: <VN className="size-5" /> },
  { code: "ID", name: "Indonesia", flag: <ID className="size-5" /> },
  { code: "MX", name: "Mexico", flag: <MX className="size-5" /> },
  { code: "CA", name: "Canada", flag: <CA className="size-5" /> },
  { code: "AE", name: "United Arab Emirates", flag: <AE className="size-5" /> },
  { code: "SA", name: "Saudi Arabia", flag: <SA className="size-5" /> },
];

const regionGroups: RegionGroup[] = [
  { name: "EU", countries: ["EU"] },
  { name: "ASEAN", countries: ["SG", "MY", "TH", "VN", "ID"] },
  { name: "USMCA", countries: ["US", "MX", "CA"] },
  { name: "GCC", countries: ["AE", "SA"] },
];

const suggestedKeywords = [
  "Tariffs",
  "Import bans",
  "Licensing",
  "Labeling",
  "Sanctions",
  "Anti-dumping",
  "Export control",
  "Safety standards",
  "Environmental compliance",
  "Cybersecurity",
];

export function AreasOfInterestView() {
  const [activeTab, setActiveTab] = useState("products");
  const [hsTree, setHsTree] = useState<HSNode[]>(hsTreeData);
  const [hsSearchQuery, setHsSearchQuery] = useState("");
  const [selectedCountries, setSelectedCountries] = useState<string[]>([]);
  const [countrySearchQuery, setCountrySearchQuery] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [keywordInput, setKeywordInput] = useState("");
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Load the saved profile from /api/v2/areas on mount.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAreas(CURRENT_USER_EMAIL)
      .then((profile) => {
        if (cancelled) return;
        setSelectedCountries(profile.countries || []);
        setKeywords(profile.keywords || []);
        const codeSet = new Set(profile.hsCodes || []);
        if (codeSet.size > 0) {
          setHsTree((prev) => applySelections(prev, codeSet));
        }
        setHasUnsavedChanges(false);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        // Fall back to sensible defaults if the API isn't reachable so the
        // UI still renders during offline dev.
        console.warn("Areas API unreachable, using defaults:", err.message);
        setSelectedCountries(["US", "CN", "IN", "EU"]);
        setKeywords(["Semiconductor", "Export control", "Safety standards"]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleHSNode = (path: number[]) => {
    const newTree = [...hsTree];
    let current: any = newTree;

    for (let i = 0; i < path.length - 1; i++) {
      current = current[path[i]].children;
    }

    const node = current[path[path.length - 1]];
    node.expanded = !node.expanded;
    setHsTree(newTree);
  };

  const toggleHSSelection = (path: number[]) => {
    const newTree = [...hsTree];
    let current: any = newTree;

    for (let i = 0; i < path.length - 1; i++) {
      current = current[path[i]].children;
    }

    const node = current[path[path.length - 1]];
    node.selected = !node.selected;

    if (node.children) {
      const setChildrenSelection = (children: HSNode[], selected: boolean) => {
        children.forEach((child) => {
          child.selected = selected;
          if (child.children) {
            setChildrenSelection(child.children, selected);
          }
        });
      };
      setChildrenSelection(node.children, node.selected || false);
    }

    setHsTree(newTree);
    setHasUnsavedChanges(true);
  };

  const getSelectedHSCodes = (nodes: HSNode[] = hsTree): string[] => {
    const selected: string[] = [];

    const traverse = (node: HSNode) => {
      if (node.selected) {
        selected.push(`${node.code} – ${node.description}`);
      }
      if (node.children) {
        node.children.forEach(traverse);
      }
    };

    nodes.forEach(traverse);
    return selected;
  };

  const removeHSCode = (code: string) => {
    const codeToRemove = code.split(" – ")[0];

    const deselectNode = (nodes: HSNode[]) => {
      nodes.forEach((node) => {
        if (node.code === codeToRemove) {
          node.selected = false;
        }
        if (node.children) {
          deselectNode(node.children);
        }
      });
    };

    const newTree = [...hsTree];
    deselectNode(newTree);
    setHsTree(newTree);
    setHasUnsavedChanges(true);
  };

  const renderHSTree = (nodes: HSNode[], path: number[] = []) => {
    return nodes.map((node, index) => {
      const currentPath = [...path, index];
      const hasChildren = node.children && node.children.length > 0;
      const level = path.length;

      return (
        <div key={node.code} style={{ marginLeft: `${level * 16}px` }}>
          <div className="flex items-center gap-2 py-2 hover:bg-muted/50 rounded px-2">
            <Checkbox
              checked={node.selected || false}
              onCheckedChange={() => toggleHSSelection(currentPath)}
              id={`hs-${node.code}`}
            />
            {hasChildren && (
              <button
                onClick={() => toggleHSNode(currentPath)}
                className="p-0 hover:bg-transparent"
              >
                {node.expanded ? (
                  <ChevronDown className="size-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="size-4 text-muted-foreground" />
                )}
              </button>
            )}
            {!hasChildren && <div className="w-4" />}
            <label
              htmlFor={`hs-${node.code}`}
              className="cursor-pointer text-sm"
              style={{
                fontWeight:
                  level === 0
                    ? "var(--font-weight-medium)"
                    : "var(--font-weight-normal)",
              }}
            >
              {node.code} – {node.description}
            </label>
          </div>
          {hasChildren && node.expanded && renderHSTree(node.children!, currentPath)}
        </div>
      );
    });
  };

  const toggleCountry = (countryCode: string) => {
    setSelectedCountries((prev) =>
      prev.includes(countryCode)
        ? prev.filter((c) => c !== countryCode)
        : [...prev, countryCode],
    );
    setHasUnsavedChanges(true);
  };

  const selectRegion = (regionName: string) => {
    const region = regionGroups.find((r) => r.name === regionName);
    if (region) {
      const newCountries = [...new Set([...selectedCountries, ...region.countries])];
      setSelectedCountries(newCountries);
      setHasUnsavedChanges(true);
    }
  };

  const filteredCountries = countries.filter((country) =>
    country.name.toLowerCase().includes(countrySearchQuery.toLowerCase()),
  );

  const addKeyword = (keyword: string) => {
    if (keyword.trim() && !keywords.includes(keyword.trim())) {
      setKeywords([...keywords, keyword.trim()]);
      setKeywordInput("");
      setHasUnsavedChanges(true);
    }
  };

  const removeKeyword = (keyword: string) => {
    setKeywords(keywords.filter((k) => k !== keyword));
    setHasUnsavedChanges(true);
  };

  const handleSave = async () => {
    setSaveError(null);
    setSaving(true);
    try {
      const profile = await saveAreas({
        email: CURRENT_USER_EMAIL,
        hsCodes: collectSelectedCodes(hsTree),
        countries: selectedCountries,
        keywords,
      });
      // Reflect the server's normalized response so the UI stays in sync
      // (countries upper-cased, dedupes applied, etc.).
      setSelectedCountries(profile.countries || []);
      setKeywords(profile.keywords || []);
      setHasUnsavedChanges(false);
    } catch (err: any) {
      setSaveError(err?.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = async () => {
    // Discard local edits and reload from the server.
    setSaveError(null);
    setLoading(true);
    try {
      const profile = await getAreas(CURRENT_USER_EMAIL);
      setSelectedCountries(profile.countries || []);
      setKeywords(profile.keywords || []);
      const codeSet = new Set(profile.hsCodes || []);
      setHsTree(applySelections(hsTreeData, codeSet));
    } catch {
      // If reload fails, just clear selections silently.
      setSelectedCountries([]);
      setKeywords([]);
      setHsTree(hsTreeData);
    } finally {
      setLoading(false);
      setHasUnsavedChanges(false);
    }
  };

  const selectedHSCodes = getSelectedHSCodes();
  const productCount = selectedHSCodes.length;
  const countryCount = selectedCountries.length;
  const keywordCount = keywords.length;

  return (
    <div className="flex flex-col h-full">
      <div className="space-y-6 flex-1 overflow-hidden flex flex-col">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-muted-foreground">
              Define what regulatory updates you care about
            </p>
          </div>
          <div className="flex items-center gap-4 px-4 py-2 rounded-md bg-muted/50 border">
            <span className="text-sm text-muted-foreground">Current Coverage:</span>
            <div className="flex items-center gap-3">
              <Badge variant="secondary" className="gap-1">
                <Package className="size-3" />
                {productCount} products
              </Badge>
              <Badge variant="secondary" className="gap-1">
                <Globe className="size-3" />
                {countryCount} countries
              </Badge>
              <Badge variant="secondary" className="gap-1">
                <Tag className="size-3" />
                {keywordCount} keywords
              </Badge>
            </div>
          </div>
        </div>

        <Tabs
          value={activeTab}
          onValueChange={setActiveTab}
          className="flex-1 flex flex-col overflow-hidden"
        >
          <TabsList>
            <TabsTrigger value="products">Products (HS Code)</TabsTrigger>
            <TabsTrigger value="geography">Geography</TabsTrigger>
            <TabsTrigger value="keywords">Keywords</TabsTrigger>
          </TabsList>

          <TabsContent value="products" className="flex-1 overflow-hidden mt-6">
            <div className="grid grid-cols-2 gap-6 h-full">
              <div className="border rounded-md bg-card flex flex-col overflow-hidden">
                <div className="p-4 border-b">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      type="text"
                      placeholder="Search HS code or product..."
                      value={hsSearchQuery}
                      onChange={(e) => setHsSearchQuery(e.target.value)}
                      className="pl-9"
                    />
                  </div>
                </div>
                <ScrollArea className="flex-1 p-4">{renderHSTree(hsTree)}</ScrollArea>
              </div>

              <div className="border rounded-md bg-card flex flex-col overflow-hidden">
                <div className="p-4 border-b flex items-center justify-between">
                  <h3 style={{ fontWeight: "var(--font-weight-medium)" }}>
                    Selected Products
                  </h3>
                  {selectedHSCodes.length > 0 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        const newTree = JSON.parse(JSON.stringify(hsTree));
                        const deselectAll = (nodes: HSNode[]) => {
                          nodes.forEach((node) => {
                            node.selected = false;
                            if (node.children) deselectAll(node.children);
                          });
                        };
                        deselectAll(newTree);
                        setHsTree(newTree);
                        setHasUnsavedChanges(true);
                      }}
                    >
                      Clear all
                    </Button>
                  )}
                </div>
                <ScrollArea className="flex-1 p-4">
                  {selectedHSCodes.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center py-12">
                      <Package className="size-12 text-muted-foreground mb-4" />
                      <p className="text-muted-foreground">No products selected</p>
                      <p className="text-sm text-muted-foreground mt-2">
                        Select HS codes from the tree to track related regulations
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {selectedHSCodes.map((code) => (
                        <div
                          key={code}
                          className="flex items-center justify-between p-3 rounded-md bg-muted/50 hover:bg-muted"
                        >
                          <span className="text-sm">{code}</span>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => removeHSCode(code)}
                            className="size-6"
                          >
                            <X className="size-4" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="geography" className="flex-1 overflow-hidden mt-6">
            <div className="grid grid-cols-2 gap-6 h-full">
              <div className="border rounded-md bg-card flex flex-col overflow-hidden">
                <div className="p-4 border-b space-y-4">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      type="text"
                      placeholder="Search countries..."
                      value={countrySearchQuery}
                      onChange={(e) => setCountrySearchQuery(e.target.value)}
                      className="pl-9"
                    />
                  </div>
                  <div className="flex gap-2">
                    {regionGroups.map((region) => (
                      <Button
                        key={region.name}
                        variant="outline"
                        size="sm"
                        onClick={() => selectRegion(region.name)}
                      >
                        {region.name}
                      </Button>
                    ))}
                  </div>
                </div>
                <ScrollArea className="flex-1 p-4">
                  <div className="space-y-1">
                    {filteredCountries.map((country) => (
                      <div
                        key={country.code}
                        className="flex items-center gap-3 p-2 hover:bg-muted/50 rounded"
                      >
                        <Checkbox
                          checked={selectedCountries.includes(country.code)}
                          onCheckedChange={() => toggleCountry(country.code)}
                          id={`country-${country.code}`}
                        />
                        <label
                          htmlFor={`country-${country.code}`}
                          className="flex items-center gap-2 cursor-pointer flex-1"
                        >
                          {country.flag}
                          <span className="text-sm">{country.name}</span>
                        </label>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </div>

              <div className="border rounded-md bg-card flex flex-col overflow-hidden">
                <div className="p-4 border-b flex items-center justify-between">
                  <h3 style={{ fontWeight: "var(--font-weight-medium)" }}>
                    Selected Countries
                  </h3>
                  {selectedCountries.length > 0 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSelectedCountries([]);
                        setHasUnsavedChanges(true);
                      }}
                    >
                      Clear all
                    </Button>
                  )}
                </div>
                <ScrollArea className="flex-1 p-4">
                  {selectedCountries.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center py-12">
                      <Globe className="size-12 text-muted-foreground mb-4" />
                      <p className="text-muted-foreground">No countries selected</p>
                      <p className="text-sm text-muted-foreground mt-2">
                        Select countries to track their regulatory changes
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {selectedCountries.map((code) => {
                        const country = countries.find((c) => c.code === code);
                        if (!country) return null;
                        return (
                          <div
                            key={code}
                            className="flex items-center justify-between p-3 rounded-md bg-muted/50 hover:bg-muted"
                          >
                            <div className="flex items-center gap-2">
                              {country.flag}
                              <span className="text-sm">{country.name}</span>
                            </div>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => toggleCountry(code)}
                              className="size-6"
                            >
                              <X className="size-4" />
                            </Button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </ScrollArea>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="keywords" className="flex-1 overflow-hidden mt-6">
            <div className="grid grid-cols-2 gap-6 h-full">
              <div className="border rounded-md bg-card flex flex-col overflow-hidden">
                <div className="p-4 border-b space-y-4">
                  <div className="relative">
                    <Input
                      type="text"
                      placeholder="Enter keyword and press Enter..."
                      value={keywordInput}
                      onChange={(e) => setKeywordInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          addKeyword(keywordInput);
                        }
                      }}
                    />
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground mb-3">
                      Suggested keywords:
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {suggestedKeywords.map((keyword) => (
                        <Button
                          key={keyword}
                          variant="outline"
                          size="sm"
                          onClick={() => addKeyword(keyword)}
                          disabled={keywords.includes(keyword)}
                        >
                          {keyword}
                        </Button>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="flex-1 p-4">
                  <p className="text-sm text-muted-foreground">
                    Keywords help refine results beyond structured filters like HS
                    codes and geography. Add terms related to regulation types,
                    compliance requirements, or specific topics you want to monitor.
                  </p>
                </div>
              </div>

              <div className="border rounded-md bg-card flex flex-col overflow-hidden">
                <div className="p-4 border-b flex items-center justify-between">
                  <h3 style={{ fontWeight: "var(--font-weight-medium)" }}>
                    Selected Keywords
                  </h3>
                  {keywords.length > 0 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setKeywords([]);
                        setHasUnsavedChanges(true);
                      }}
                    >
                      Clear all
                    </Button>
                  )}
                </div>
                <ScrollArea className="flex-1 p-4">
                  {keywords.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center py-12">
                      <Tag className="size-12 text-muted-foreground mb-4" />
                      <p className="text-muted-foreground">No keywords selected</p>
                      <p className="text-sm text-muted-foreground mt-2">
                        Add keywords to refine your alert relevance
                      </p>
                    </div>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {keywords.map((keyword) => (
                        <Badge
                          key={keyword}
                          variant="secondary"
                          className="gap-2 py-2 px-3"
                        >
                          {keyword}
                          <button
                            onClick={() => removeKeyword(keyword)}
                            className="hover:text-destructive"
                          >
                            <X className="size-3" />
                          </button>
                        </Badge>
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </div>

      <div className="sticky bottom-0 -mx-6 mt-6 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex items-center justify-between px-6 py-4">
          <div>
            {saveError ? (
              <p className="text-sm text-red-600">Save failed: {saveError}</p>
            ) : hasUnsavedChanges ? (
              <p className="text-sm text-muted-foreground">
                You have unsaved changes
              </p>
            ) : null}
          </div>
          <div className="flex gap-3">
            <Button
              variant="outline"
              onClick={handleCancel}
              disabled={saving || loading}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={!hasUnsavedChanges || saving}
            >
              {saving ? "Saving…" : "Save Areas of Interest"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
