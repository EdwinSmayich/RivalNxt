import { useEffect, useMemo, useState } from "react";
import { Loader2, Undo2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { Input } from "./ui/input";
import { editVoiceLine, getVoiceLines, type VoiceLine, type VoiceMod } from "../lib/api";

type Filter = "spoken" | "silent" | "kept" | "edited";

const FILTERS: { id: Filter; label: string; test: (line: VoiceLine) => boolean }[] = [
  { id: "spoken", label: "Spoken", test: (l) => l.status === "changed" && !l.left_as_in_game },
  { id: "silent", label: "Silenced", test: (l) => l.status === "silent" },
  { id: "kept", label: "Kept as in the game", test: (l) => l.left_as_in_game },
  { id: "edited", label: "Edited", test: (l) => l.edited },
];

function LineRow({
  line,
  english,
  onSave,
}: {
  line: VoiceLine;
  english: boolean;
  onSave: (text: string | null) => Promise<void>;
}) {
  const [text, setText] = useState(line.subtitle ?? "");
  const [saving, setSaving] = useState(false);
  useEffect(() => setText(line.subtitle ?? ""), [line.subtitle]);

  const save = async (value: string | null) => {
    if (value !== null && value.trim() === (line.subtitle ?? "").trim()) return;
    setSaving(true);
    try {
      await onSave(value);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="py-3 border-b last:border-b-0 space-y-1.5">
      <div className="grid gap-x-4 gap-y-1 text-sm md:grid-cols-2">
        <div>
          <div className="text-xs text-muted-foreground">In the game</div>
          <div title={!english && line.game_en ? line.game_en : undefined}>{line.game || "—"}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">Heard in the mod</div>
          <div className={line.status === "silent" ? "italic text-muted-foreground" : ""}>
            {line.status === "silent" ? "silence" : line.heard || "—"}
          </div>
        </div>
      </div>
      {line.left_as_in_game ? (
        <div className="text-xs text-muted-foreground">Keeps the game's subtitle.</div>
      ) : (
        <div className="flex items-center gap-2">
          <Input
            value={text}
            placeholder={line.status === "silent" ? "No subtitle" : "Subtitle"}
            onChange={(e) => setText(e.target.value)}
            onBlur={() => save(text)}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              if (e.key === "Escape") setText(line.subtitle ?? "");
            }}
            data-dirty={text !== (line.subtitle ?? "")}
            aria-label="Subtitle"
          />
          {saving && <Loader2 className="h-4 w-4 animate-spin shrink-0" />}
          {line.edited && !saving && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => save(null)}
              title="Take the edit back"
              aria-label="Take the edit back"
            >
              <Undo2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

export function VoiceLinesDialog({
  mod,
  language,
  languageName,
  onClose,
}: {
  mod: VoiceMod;
  language: string;
  languageName: string;
  onClose: () => void;
}) {
  const [lines, setLines] = useState<VoiceLine[] | null>(null);
  const [filter, setFilter] = useState<Filter | null>(null);
  const [search, setSearch] = useState("");

  const load = async () => {
    try {
      setLines((await getVoiceLines(mod.key, language)).lines);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
      onClose();
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mod.key, language]);

  const counts = useMemo(() => {
    const out = {} as Record<Filter, number>;
    for (const f of FILTERS) out[f.id] = (lines ?? []).filter(f.test).length;
    return out;
  }, [lines]);

  // Open on what the voice mod says; a mod that only silences lines opens on those.
  const current: Filter = filter ?? (counts.spoken > 0 || counts.silent === 0 ? "spoken" : "silent");

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const test = FILTERS.find((f) => f.id === current)!.test;
    return (lines ?? []).filter((line) => {
      if (!needle) return test(line);
      return [line.game, line.game_en, line.heard, line.subtitle].some((t) => (t ?? "").toLowerCase().includes(needle));
    });
  }, [lines, current, search]);

  const save = async (line: VoiceLine, text: string | null) => {
    try {
      await editVoiceLine(mod.key, language, line.key, text);
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        className="sm:max-w-4xl max-h-[85vh] flex flex-col"
        onEscapeKeyDown={(e) => {
          // Escape in a line being typed undoes the typing; the next one closes.
          if ((document.activeElement as HTMLElement | null)?.dataset.dirty === "true") e.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle className="pr-6 break-words">
            {mod.hero_name} · {mod.name.replace(/_\d+_P\.pak$/i, "")}
          </DialogTitle>
          <DialogDescription>
            {languageName} subtitles. Change a line and press Enter: the subtitle mod is rewritten
            {language === "en" ? "." : ", and your corrections guide the translation of other lines."}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map((f) => (
            <Button
              key={f.id}
              size="sm"
              variant={!search && current === f.id ? "secondary" : "ghost"}
              onClick={() => {
                setFilter(f.id);
                setSearch("");
              }}
              disabled={counts[f.id] === 0 && f.id !== "spoken"}
            >
              {f.label}
              {lines && (
                <Badge variant="outline" className="ml-1 tabular-nums">
                  {counts[f.id]}
                </Badge>
              )}
            </Button>
          ))}
          <Input
            className="ml-auto w-56"
            placeholder="Search all lines"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search lines"
          />
        </div>
        <div className="flex-1 overflow-y-auto pr-1">
          {lines === null ? (
            <div className="flex items-center gap-2 py-8 justify-center text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          ) : shown.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">No lines here.</div>
          ) : (
            shown.map((line) => (
              <LineRow key={line.key} line={line} english={language === "en"} onSave={(text) => save(line, text)} />
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
