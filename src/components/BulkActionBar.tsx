import { useState } from "react";
import { Button } from "./ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "./ui/alert-dialog";
import { Check, Loader2, Power, PowerOff, Tag, Trash2, X } from "lucide-react";

/**
 * Actions for the mods currently selected.
 *
 * A library of 200+ mods could only be operated one card at a time, so
 * "disable everything for this character" meant two hundred clicks and two
 * hundred conflict rebuilds. The rebuild is the expensive part, which is why
 * enable/disable go through a single batched request rather than a loop here.
 */
export function BulkActionBar({
  count,
  total,
  busy,
  onEnable,
  onDisable,
  onTag,
  onDelete,
  onSelectAll,
  onClear,
}: {
  count: number;
  total: number;
  busy: boolean;
  onEnable: () => void;
  onDisable: () => void;
  onTag: (tag: string) => void;
  onDelete: () => void;
  onSelectAll: () => void;
  onClear: () => void;
}) {
  const [tagOpen, setTagOpen] = useState(false);
  const [tagValue, setTagValue] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div
      className="flex items-center gap-2 flex-wrap px-4 py-2 border-b border-border"
      style={{ background: "hsl(var(--primary) / 0.06)" }}
    >
      <span className="text-sm font-medium tabular-nums">
        {count} selected
      </span>

      <Button
        variant="ghost"
        size="sm"
        className="h-7 text-xs"
        disabled={busy}
        onClick={count === total ? onClear : onSelectAll}
      >
        {count === total ? "Clear" : `Select all ${total}`}
      </Button>

      <div className="flex-1" />

      <Button
        variant="outline"
        size="sm"
        className="h-8 gap-1.5"
        disabled={busy || count === 0}
        onClick={onEnable}
      >
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Power className="w-3.5 h-3.5" />}
        Enable
      </Button>
      <Button
        variant="outline"
        size="sm"
        className="h-8 gap-1.5"
        disabled={busy || count === 0}
        onClick={onDisable}
      >
        <PowerOff className="w-3.5 h-3.5" />
        Disable
      </Button>
      <Button
        variant="outline"
        size="sm"
        className="h-8 gap-1.5"
        disabled={busy || count === 0}
        onClick={() => {
          setTagValue("");
          setTagOpen(true);
        }}
      >
        <Tag className="w-3.5 h-3.5" />
        Tag
      </Button>
      <Button
        variant="outline"
        size="sm"
        className="h-8 gap-1.5 text-destructive hover:text-destructive"
        disabled={busy || count === 0}
        onClick={() => setConfirmDelete(true)}
      >
        <Trash2 className="w-3.5 h-3.5" />
        Delete
      </Button>

      <Button
        variant="ghost"
        size="sm"
        className="h-8 w-8 p-0"
        onClick={onClear}
        aria-label="Leave selection mode"
      >
        <X className="w-4 h-4" />
      </Button>

      <AlertDialog open={tagOpen} onOpenChange={setTagOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Tag {count} mod{count === 1 ? "" : "s"}</AlertDialogTitle>
            <AlertDialogDescription>
              Adds one tag. Mods that already have it are left alone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <input
            value={tagValue}
            onChange={(e) => setTagValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && tagValue.trim()) {
                e.preventDefault();
                onTag(tagValue.trim());
                setTagOpen(false);
              }
            }}
            placeholder="Tag name"
            maxLength={40}
            autoFocus
            className="w-full text-sm bg-background border border-border rounded-lg px-2.5 py-2"
          />
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={!tagValue.trim()}
              onClick={(e) => {
                e.preventDefault();
                onTag(tagValue.trim());
                setTagOpen(false);
              }}
            >
              <Check className="w-3.5 h-3.5 mr-1.5" />
              Add tag
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete {count} mod{count === 1 ? "" : "s"}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This removes their archives from disk and their entries from the
              database. It cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                setConfirmDelete(false);
                onDelete();
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
