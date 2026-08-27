import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { clearActivity, listActivity, type ActivityEntry } from "../lib/api";

/** Colour per kind, so the list can be skimmed rather than read. */
const KIND_STYLE: Record<string, { label: string; color: string }> = {
  activated: { label: "on", color: "#22c55e" },
  deactivated: { label: "off", color: "#94a3b8" },
  changed: { label: "changed", color: "#38bdf8" },
  file_hidden: { label: "hidden", color: "#f59e0b" },
  file_restored: { label: "restored", color: "#a855f7" },
  backup: { label: "backup", color: "#8b5cf6" },
  restored: { label: "restore", color: "#f97316" },
  deleted: { label: "deleted", color: "#ef4444" },
  tagged: { label: "tagged", color: "#14b8a6" },
};

function when(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const minutes = Math.round((Date.now() - at.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
  return at.toLocaleDateString();
}

/**
 * What the app has done recently.
 *
 * Every one of these actions already reported itself in a toast that was gone
 * four seconds later. "Did that apply?" previously meant reading backend.log,
 * which is a developer artifact.
 */
export function ActivityDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [entries, setEntries] = useState<ActivityEntry[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const rows = await listActivity(200);
        if (!cancelled) setEntries(rows);
      } catch {
        if (!cancelled) setEntries([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const handleClear = async () => {
    try {
      await clearActivity();
      setEntries([]);
      toast.success("History cleared");
    } catch (err) {
      toast.error(
        `Could not clear: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl" style={{ maxHeight: "80vh" }}>
        <DialogHeader>
          <DialogTitle>History</DialogTitle>
          <DialogDescription>
            What this app changed, newest first. The last 500 actions are kept.
          </DialogDescription>
        </DialogHeader>

        <div style={{ maxHeight: "55vh", overflowY: "auto" }} className="pr-1">
          {loading ? (
            <div className="flex items-center justify-center py-10 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : entries.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              Nothing yet. Turn a mod on and it will show up here.
            </p>
          ) : (
            <div className="flex flex-col gap-1.5">
              {entries.map((entry) => {
                const style = KIND_STYLE[entry.kind] ?? {
                  label: entry.kind,
                  color: "#94a3b8",
                };
                return (
                  <div
                    key={entry.id}
                    className="flex items-start gap-3 rounded-lg px-2.5 py-2 bg-muted/30"
                  >
                    <span
                      className="text-xs px-1.5 py-0.5 rounded shrink-0 mt-0.5 font-medium"
                      style={{
                        background: `${style.color}22`,
                        color: style.color,
                        minWidth: "62px",
                        textAlign: "center",
                      }}
                    >
                      {style.label}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm truncate">{entry.summary}</p>
                      {entry.detail ? (
                        <p className="text-xs text-muted-foreground truncate">
                          {entry.detail}
                        </p>
                      ) : null}
                    </div>
                    <span className="text-xs text-muted-foreground/70 shrink-0 mt-0.5">
                      {when(entry.at)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {entries.length > 0 ? (
          <div className="flex justify-end pt-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void handleClear()}
              className="gap-1.5 text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Clear history
            </Button>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
