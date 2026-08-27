import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Input } from "./ui/input";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  ExternalLink,
  Loader2,
  Search,
  ThumbsUp,
  X,
} from "lucide-react";
import { toast } from "sonner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import {
  browseNexus,
  listNexusCategories,
  type NexusBrowseMod,
  type NexusSortField,
} from "../lib/api";
import { AdultContentToggle } from "./AdultContentToggle";
import { openInBrowser } from "../lib/tauri-utils";

/** Radix Select forbids an empty item value, so "no filter" needs a sentinel. */
const ALL = "__all__";

const PAGE_SIZE = 30;

/** Typing shouldn't fire a request per keystroke. */
const SEARCH_DEBOUNCE_MS = 350;

const SORTS: { value: NexusSortField; label: string }[] = [
  { value: "endorsements", label: "Most endorsed" },
  { value: "downloads", label: "Most downloaded" },
  { value: "createdAt", label: "Newest" },
  { value: "updatedAt", label: "Recently updated" },
  { value: "name", label: "Name" },
];

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function since(iso: string | null): string {
  if (!iso) return "";
  const days = Math.round((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (Number.isNaN(days)) return "";
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.round(days / 30)}mo ago`;
  return `${Math.round(days / 365)}y ago`;
}

export function NexusBrowseView() {
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  // Newest by default: the tab is for finding what has just appeared, and
  // "most endorsed" shows the same handful of famous mods every time.
  const [sortBy, setSortBy] = useState<NexusSortField>("createdAt");
  const [category, setCategory] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [showAdult, setShowAdult] = useState(true);

  const [mods, setMods] = useState<NexusBrowseMod[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Guards against a slow early page landing after a newer search returned.
  const requestSeq = useRef(0);
  // Read inside the fetch so "load more" does not need mods.length as a dep,
  // which would re-run the effect and refetch page 1 after every append.
  const loadedCount = useRef(0);

  useEffect(() => {
    listNexusCategories()
      .then(setCategories)
      .catch(() => setCategories([]));
  }, []);

  // Search as you type, once typing pauses.
  useEffect(() => {
    const t = setTimeout(() => setQuery(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [searchInput]);

  const runSearch = useCallback(
    async (append: boolean) => {
      const seq = ++requestSeq.current;
      if (append) setLoadingMore(true);
      else setLoading(true);
      setError(null);
      try {
        const result = await browseNexus({
          query: query || undefined,
          category: category || undefined,
          sortBy,
          includeAdult: showAdult,
          offset: append ? loadedCount.current : 0,
          count: PAGE_SIZE,
        });
        if (seq !== requestSeq.current) return;
        setMods((prev) => {
          const next = append ? [...prev, ...result.mods] : result.mods;
          loadedCount.current = next.length;
          return next;
        });
        setTotal(result.total);
        setHasMore(result.has_more);
      } catch (err: any) {
        if (seq !== requestSeq.current) return;
        setError(err?.message ?? String(err));
        if (!append) {
          setMods([]);
          loadedCount.current = 0;
        }
      } finally {
        if (seq === requestSeq.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [query, category, sortBy, showAdult],
  );

  useEffect(() => {
    void runSearch(false);
  }, [runSearch]);

  const handleOpen = async (mod: NexusBrowseMod) => {
    if (!mod.modPageUrl) return;
    try {
      await openInBrowser(mod.modPageUrl);
      toast.info(`Opened "${mod.name}" on Nexus`, {
        description: 'Click "Mod Manager Download" — it lands back here.',
        duration: 6000,
      });
    } catch (err: any) {
      toast.error(`Could not open the mod page: ${err?.message ?? String(err)}`);
    }
  };

  const activeFilters = [
    query && { label: `"${query}"`, clear: () => { setSearchInput(""); setQuery(""); } },
    category && { label: category, clear: () => setCategory("") },
    !showAdult && { label: "SFW only", clear: () => setShowAdult(true) },
  ].filter(Boolean) as { label: string; clear: () => void }[];

  return (
    <div className="flex flex-col h-full">
      {/* The grid lives here rather than relying on `.mods-grid`, which is
          injected by ActiveModsView's inline <style> and therefore does not
          exist while this tab is mounted — that is why every card previously
          stretched to the full width of the window. */}
      <style>{`
        .nexus-grid {
          display: grid;
          gap: 1rem;
          grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
        }
        .nexus-card-media {
          position: relative;
          aspect-ratio: 16 / 9;
          overflow: hidden;
          background: hsl(var(--muted));
        }
        .nexus-card-media img {
          width: 100%;
          height: 100%;
          object-fit: cover;
          transition: transform 0.25s ease;
        }
        .nexus-card:hover .nexus-card-media img { transform: scale(1.04); }
        .nexus-clamp-2 {
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
      `}</style>

      {/* Toolbar */}
      <div className="border-b border-border bg-card px-6 py-3 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            <Input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search Marvel Rivals mods by name…"
              className="pl-9 pr-9"
            />
            {searchInput && (
              <button
                onClick={() => setSearchInput("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-full hover:bg-accent"
                aria-label="Clear search"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Radix Select, not a native one. The browser draws the native
              dropdown itself and ignores the app's colours, so on Windows it
              opened as a white panel with near-invisible text over the dark UI.
              This renders its own list in a portal we control. */}
          <Select
            value={category || ALL}
            onValueChange={(v) => setCategory(v === ALL ? "" : v)}
          >
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="All categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All categories</SelectItem>
              {categories.map((c) => (
                <SelectItem key={c} value={c}>{c}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={sortBy} onValueChange={(v) => setSortBy(v as NexusSortField)}>
            <SelectTrigger className="w-[170px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORTS.map((s) => (
                <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Lit red outline when on, matching the header's destructive
              actions, so "adult content is showing" is visible at a glance
              rather than needing the label to be read. */}
          <AdultContentToggle
            shown={showAdult}
            onToggle={() => setShowAdult((v) => !v)}
            className="shrink-0 h-9"
          />
        </div>

        <div className="flex items-center gap-2 flex-wrap min-h-[22px]">
          <span className="text-xs text-muted-foreground">
            {loading
              ? "Searching…"
              : total > 0
                ? `${total.toLocaleString()} mods`
                : query
                  ? "No matches"
                  : "Browsing"}
          </span>
          {activeFilters.map((f) => (
            <Badge
              key={f.label}
              variant="secondary"
              className="text-xs gap-1 cursor-pointer hover:bg-destructive/20"
              onClick={f.clear}
            >
              {f.label}
              <X className="w-3 h-3" />
            </Badge>
          ))}
        </div>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-auto custom-scrollbar">
        <div className="p-6">
          {error && (
            <div className="flex items-start gap-3 p-4 rounded-lg border border-amber-500/30 bg-amber-500/10 mb-4">
              <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-amber-300">Could not reach Nexus</p>
                <p className="text-xs text-muted-foreground mt-0.5">{error}</p>
                <Button variant="outline" size="sm" className="mt-2" onClick={() => void runSearch(false)}>
                  Try again
                </Button>
              </div>
            </div>
          )}

          {loading && mods.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 gap-3">
              <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">Searching Nexus…</p>
            </div>
          )}

          {mods.length > 0 && (
            <div className="nexus-grid">
              {mods.map((mod) => {
                // No per-card unblurring: turning "18+ shown" on is already the
                // decision to see it, and asking again on every card was just
                // friction.
                return (
                  <div
                    key={mod.modId}
                    className="nexus-card rounded-lg border border-border bg-card overflow-hidden flex flex-col hover:border-primary/40 transition-colors"
                  >
                    <div className="nexus-card-media">
                      {mod.thumbnailUrl ? (
                        <img src={mod.thumbnailUrl} alt={mod.name} loading="lazy" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-muted-foreground text-xs">
                          No image
                        </div>
                      )}

                      {mod.adult && (
                        <Badge variant="destructive" className="absolute top-2 right-2 text-xs">
                          18+
                        </Badge>
                      )}
                      {mod.isInstalled && (
                        <Badge className="absolute top-2 left-2 text-xs gap-1 bg-emerald-600 hover:bg-emerald-600">
                          <CheckCircle2 className="w-3 h-3" />
                          Installed
                        </Badge>
                      )}
                      {mod.category && (
                        <Badge
                          variant="secondary"
                          className="absolute bottom-2 left-2 text-xs"
                          style={{ background: "rgba(0,0,0,0.65)", color: "white" }}
                        >
                          {mod.category}
                        </Badge>
                      )}
                    </div>

                    <div className="p-3 flex flex-col gap-1.5 flex-1">
                      <h3
                        className="text-sm font-medium leading-snug nexus-clamp-2"
                        title={mod.name}
                      >
                        {mod.name}
                      </h3>
                      <p className="text-xs text-muted-foreground truncate">
                        {mod.author || "unknown"}
                        {mod.updatedAt ? ` · ${since(mod.updatedAt)}` : ""}
                      </p>

                      <div className="flex items-center gap-3 text-xs text-muted-foreground mt-auto pt-1">
                        <span className="flex items-center gap-1" title="Downloads">
                          <Download className="w-3 h-3" />
                          {compact(mod.downloads)}
                        </span>
                        <span className="flex items-center gap-1" title="Endorsements">
                          <ThumbsUp className="w-3 h-3" />
                          {compact(mod.endorsements)}
                        </span>
                      </div>

                      {/* Outline, not a filled button. Sixty solid white blocks
                          in a grid pull the eye away from the artwork, which is
                          what the page is actually for. */}
                      <Button
                        size="sm"
                        variant="outline"
                        className="w-full gap-2 mt-1 h-8 text-xs"
                        onClick={() => handleOpen(mod)}
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        {mod.isInstalled ? "Open on Nexus" : "Get mod"}
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {hasMore && (
            <div className="flex justify-center mt-6">
              <Button
                variant="outline"
                onClick={() => void runSearch(true)}
                disabled={loadingMore}
                className="gap-2"
              >
                {loadingMore ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Loading…
                  </>
                ) : (
                  `Load more — ${mods.length} of ${total.toLocaleString()}`
                )}
              </Button>
            </div>
          )}

          {!loading && !error && mods.length === 0 && (
            <div className="text-center py-16">
              <h3 className="text-lg font-medium mb-2">No mods found</h3>
              <p className="text-muted-foreground text-sm">
                {query
                  ? `Nothing matched "${query}".`
                  : "Try a different category or sort order."}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
