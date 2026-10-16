/**
 * Subtitles under a voice mod's .pak in a mod's Files tab: whether they are
 * made, on or being made, with the one action that fits.
 *
 * Switching a voice mod on brings its subtitle mod with it (the backend does
 * that); this row shows the result, and makes or switches subtitles from here.
 */
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { Captions, Loader2, Play } from "lucide-react";
import { toast } from "sonner";

import { Button } from "./ui/button";
import { Switch } from "./ui/switch";
import { HeroIcon } from "./HeroIcon";
import {
  getVoiceSubtitlesForDownloads,
  makeVoiceSubtitles,
  setActivePaks,
  type VoiceDownloadSubtitles,
} from "../lib/api";

const FAST_MS = 2000;
const SLOW_MS = 10000;
const FAST_AFTER_CHANGE_MS = 30000; // the backend follows a voice mod switched on within seconds

export type VoicePakSubtitlesState = { data: VoiceDownloadSubtitles | null; refresh: () => void };

/** What the backend knows of the voice mods in these downloads; asked again while something may change. */
export function useVoicePakSubtitles(downloadIds: number[], enabled: boolean, changeKey: string): VoicePakSubtitlesState {
  const [data, setData] = useState<VoiceDownloadSubtitles | null>(null);
  const [nonce, setNonce] = useState(0);
  const idsKey = useMemo(() => [...downloadIds].sort((a, b) => a - b).join(","), [downloadIds]);

  useEffect(() => {
    if (!enabled || !idsKey) {
      setData(null);
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const fastUntil = Date.now() + FAST_AFTER_CHANGE_MS;
    const tick = async () => {
      try {
        const next = await getVoiceSubtitlesForDownloads(idsKey.split(",").map(Number));
        if (!alive) return;
        setData(next);
        const voice = Object.values(next.paks).flatMap((byPak) => Object.values(byPak));
        if (voice.length === 0 && !next.scanning) return; // no voice mod here: nothing to follow
        const busy = next.scanning || voice.some((info) => info.job);
        timer = setTimeout(tick, busy || Date.now() < fastUntil ? FAST_MS : SLOW_MS);
      } catch {
        if (alive) timer = setTimeout(tick, SLOW_MS);
      }
    };
    void tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, idsKey, changeKey, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  return { data, refresh };
}

function basename(path: string): string {
  return (path.split(/[/\\]/).pop() || path).toLowerCase();
}

export function VoicePakSubtitlesRow({
  state,
  downloadId,
  pak,
}: {
  state: VoicePakSubtitlesState;
  downloadId: number;
  pak: string;
}) {
  const [busy, setBusy] = useState(false);
  const info = state.data?.paks[String(downloadId)]?.[basename(pak)];
  if (!state.data || !info) return null;
  const { language, language_name: languageName, not_ready: notReady } = state.data;
  const sub = info.subtitles;
  const job = info.job;

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
      state.refresh();
    }
  };

  let label: string;
  let control: ReactNode = null;
  if (info.skipped) {
    label = `Subtitles are not made for ${info.hero_name}`;
  } else if (job) {
    const pct = job.total ? ` ${Math.round((job.done / job.total) * 100)}%` : "";
    label = `Making ${languageName} subtitles · ${job.stage || "waiting for its turn"}${pct}`;
    control = <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />;
  } else if (sub.state === "ready") {
    label = `${languageName} subtitles · ${sub.counts?.subtitled ?? 0} lines${sub.shared ? " · shared file" : ""}`;
    control = (
      <label className="flex items-center gap-2">
        <Switch
          checked={sub.active}
          disabled={busy || sub.download_id == null}
          onCheckedChange={(on) =>
            act(() => setActivePaks(sub.download_id as number, on ? [sub.pak] : []))
          }
          aria-label="Subtitles on"
        />
        <span>{sub.active ? "On" : "Off"}</span>
      </label>
    );
  } else {
    label =
      sub.state === "partial"
        ? `${languageName} subtitles · ${sub.counts?.missing ?? 0} lines still to translate`
        : `No ${languageName} subtitles yet`;
    control = (
      <Button
        size="sm"
        variant="outline"
        className="h-7 px-2 text-xs"
        disabled={busy || !!notReady}
        title={notReady ?? undefined}
        onClick={() => act(() => makeVoiceSubtitles(info.key, language))}
      >
        <Play className="h-3 w-3" /> {sub.state === "partial" ? "Continue" : "Make subtitles"}
      </Button>
    );
  }

  return (
    <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2 text-xs" style={{ paddingLeft: 28 }}>
      <div className="flex items-center gap-2 min-w-0 text-muted-foreground">
        <HeroIcon avatar={info.avatar} name={info.hero_name} className="h-5 w-5" />
        <Captions className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{label}</span>
        {notReady && !info.skipped && sub.state === "none" && !job && (
          <span className="text-amber-500 truncate">· {notReady}</span>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">{control}</div>
    </div>
  );
}
