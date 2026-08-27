import React, { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import type { Mod } from "./ModCard";
import { AlertCircle, CheckCircle2, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { assignModId, suggestModIds, type ModIdSuggestion } from "../lib/api";

/**
 * Pull a mod id out of whatever the user pasted.
 *
 * People copy the whole address far more often than they read the number out of
 * it, and "https://www.nexusmods.com/marvelrivals/mods/11133?tab=files" was
 * simply rejected as non-numeric.
 */
function parseModId(raw: string): number | null {
  const text = raw.trim();
  if (!text) return null;
  const fromUrl = text.match(/\/mods\/(\d+)/);
  const digits = fromUrl ? fromUrl[1] : text.match(/^\d+$/)?.[0];
  if (!digits) return null;
  const value = parseInt(digits, 10);
  return Number.isFinite(value) && value > 0 ? value : null;
}

interface AssignModIdModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mod: Mod | null;
  onSuccess: (modId: string, nexusId: number) => void;
}

export function AssignModIdModal({ open, onOpenChange, mod, onSuccess }: AssignModIdModalProps) {
  const [nexusIdInput, setNexusIdInput] = useState("");
  const [status, setStatus] = useState<"idle" | "verifying" | "renamed" | "failed">("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [suggestions, setSuggestions] = useState<ModIdSuggestion[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);

  const downloadId = (mod?.sourceDownloadIds ?? [])[0];

  // Offered rather than applied. The guess comes from the file name and tags,
  // and a wrong id silently attaches another mod's artwork and changelog, so
  // the choice stays with the user.
  useEffect(() => {
    if (!open || downloadId == null) {
      setSuggestions([]);
      return;
    }
    let cancelled = false;
    setLoadingSuggestions(true);
    void (async () => {
      try {
        const result = await suggestModIds(Number(downloadId));
        if (!cancelled) setSuggestions(result.suggestions);
      } catch {
        if (!cancelled) setSuggestions([]);
      } finally {
        if (!cancelled) setLoadingSuggestions(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, downloadId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mod || !nexusIdInput.trim()) return;

    const parsedId = parseModId(nexusIdInput);
    if (parsedId == null) {
      setStatus("failed");
      setErrorMsg("Enter a mod ID or paste the mod's Nexus address.");
      return;
    }

    setStatus("verifying");
    setErrorMsg("");

    try {
      const response = await assignModId({
        local_paths: mod.sourcePaths || [mod.id],
        nexus_mod_id: parsedId,
        game: "marvelrivals"
      });

      if (response.ok) {
        setStatus("renamed");
        onSuccess(mod.id, parsedId);
        setTimeout(() => {
          onOpenChange(false);
          setStatus("idle");
          setNexusIdInput("");
        }, 1500);
      } else {
        setStatus("failed");
        setErrorMsg(response.error || "Failed to assign Mod ID.");
      }
    } catch (err: any) {
      setStatus("failed");
      setErrorMsg(err.message || "An unexpected error occurred.");
    }
  };

  const handleClose = () => {
    if (status === "verifying") return;
    onOpenChange(false);
    setTimeout(() => {
      setStatus("idle");
      setNexusIdInput("");
      setErrorMsg("");
    }, 200);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      {/* Bounded and scrollable. The suggestion list is as long as the search
          result, so on some mods the dialog grew past the bottom of the window
          and took the Cancel / Verify buttons with it. */}
      <DialogContent
        className="sm:max-w-[520px] flex flex-col"
        style={{ maxHeight: "min(85vh, 700px)" }}
      >
        <DialogHeader>
          <DialogTitle>Assign Mod ID</DialogTitle>
          <DialogDescription>
            Enter the Nexus Mod ID for <strong>{mod?.name}</strong> to link it to the Nexus API and enable updates. 
            The ID can be found in the URL of the mod's Nexus page (e.g., .../mods/<strong>123</strong>).
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col min-h-0 flex-1 gap-4 py-2">
          <div className="space-y-2 shrink-0">
            <Input
              id="nexusId"
              placeholder="11133  —  or paste the mod's address"
              value={nexusIdInput}
              onChange={(e) => setNexusIdInput(e.target.value)}
              disabled={status === "verifying" || status === "renamed"}
              autoFocus
            />
          </div>

          {/* Candidates worked out from the file name and tags. */}
          {(loadingSuggestions || suggestions.length > 0) && (
            <div className="flex flex-col min-h-0 flex-1">
              <p className="text-sm font-medium mb-1.5 shrink-0">
                {loadingSuggestions ? "Looking for matches…" : "Might be one of these"}
              </p>
              {loadingSuggestions ? (
                <div className="flex justify-center py-4 text-muted-foreground">
                  <Loader2 className="w-4 h-4 animate-spin" />
                </div>
              ) : (
                // pr-2 keeps the row borders clear of the scrollbar, which
                // otherwise sat on top of the right-hand edge.
                <div
                  className="flex flex-col gap-1.5 min-h-0 flex-1 pr-2"
                  style={{ overflowY: "auto" }}
                >
                  {suggestions.map((s) => {
                    const picked = parseModId(nexusIdInput) === s.modId;
                    return (
                      <button
                        key={s.modId}
                        type="button"
                        onClick={() => setNexusIdInput(String(s.modId))}
                        disabled={status === "verifying" || status === "renamed"}
                        className="flex items-center gap-2.5 rounded-lg border p-1.5 text-left transition-colors hover:bg-accent disabled:opacity-50"
                        style={{
                          borderColor: picked
                            ? "hsl(var(--primary))"
                            : "hsl(var(--border))",
                        }}
                      >
                        {s.thumbnail ? (
                          <img
                            src={s.thumbnail}
                            alt=""
                            className="rounded object-cover shrink-0"
                            style={{ width: "48px", height: "34px" }}
                            loading="lazy"
                          />
                        ) : (
                          <span
                            className="rounded bg-muted shrink-0"
                            style={{ width: "48px", height: "34px" }}
                          />
                        )}
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm truncate">{s.name}</span>
                          <span className="block text-xs text-muted-foreground truncate">
                            {s.modId} · {s.author}
                          </span>
                        </span>
                        <a
                          href={s.modPageUrl}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="p-1 text-muted-foreground hover:text-foreground shrink-0"
                          title="Open on Nexus to check"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
          {status === "verifying" && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <RefreshCw className="w-4 h-4 animate-spin" />
              Verifying files with Nexus API...
            </div>
          )}
          {status === "renamed" && (
            <div className="flex items-center gap-2 text-sm text-emerald-500">
              <CheckCircle2 className="w-4 h-4" />
              Mod ID assigned and files renamed!
            </div>
          )}
          {status === "failed" && (
            <div className="flex items-start gap-2 text-sm text-destructive">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <p>{errorMsg}</p>
            </div>
          )}
          <DialogFooter className="shrink-0">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              disabled={status === "verifying"}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!nexusIdInput.trim() || status === "verifying" || status === "renamed"}
            >
              Verify & Assign
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
