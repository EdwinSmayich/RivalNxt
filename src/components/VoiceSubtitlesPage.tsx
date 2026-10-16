import { type ReactNode, useCallback, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  AlertTriangle,
  Captions,
  Check,
  Cpu,
  FolderOpen,
  HardDrive,
  Info,
  Languages,
  ListChecks,
  Loader2,
  Mic,
  Pencil,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Switch } from "./ui/switch";
import { VoiceLinesDialog } from "./VoiceLinesDialog";
import {
  cancelVoiceJob,
  getVoiceSubtitles,
  installVoiceComponent,
  makeAllVoiceSubtitles,
  makeVoiceSubtitles,
  removeVoiceComponent,
  rescanVoiceMods,
  setActivePaks,
  setVoiceSubtitlesSettings,
  type VoiceJob,
  type VoiceMod,
  type VoiceModelChoice,
  type VoiceSubtitlesStatus,
} from "../lib/api";
import { useAdaptivePoll } from "../lib/intervalHelpers";

export function gigabytes(bytes: number | null | undefined): string {
  if (!bytes) return "0 GB";
  const gb = bytes / 1e9;
  return gb >= 10 ? `${Math.round(gb)} GB` : `${gb.toFixed(1)} GB`;
}

export function timeLeft(seconds: number): string {
  if (seconds < 60) return "less than a minute left";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `about ${minutes} min left`;
  return `about ${Math.floor(minutes / 60)} h ${minutes % 60} min left`;
}

const FIT: Record<VoiceModelChoice["fit"], { label: string; className: string }> = {
  gpu: { label: "Runs on your graphics card", className: "text-emerald-500" },
  split: { label: "Partly on the processor", className: "text-sky-500" },
  // Measured: the 26B-A4B on a processor alone is no slower than on an 8 GB card.
  slow: { label: "Runs on the processor", className: "text-sky-500" },
  no: { label: "Too big for this computer", className: "text-red-500" },
};

const ACTIVE_STATES = new Set(["queued", "running", "waiting"]);
const SEARCH_FROM = 6; // voice mods before the list gets a search box

const isRecognitionJob = (job: VoiceJob) => /whisper|vgmstream/.test(job.target);

function percent(job: VoiceJob): number | null {
  if (!job.total) return null;
  return Math.max(0, Math.min(100, Math.round((job.done / job.total) * 100)));
}

function JobProgress({ job, onCancel }: { job: VoiceJob; onCancel?: () => void }) {
  const pct = percent(job);
  const waiting = job.state === "waiting" || job.state === "queued";
  const running = job.state === "running";
  const unit = job.kind === "install" ? `${gigabytes(job.done)} of ${gigabytes(job.total)}` : `${job.done} of ${job.total}`;
  const label = job.state === "queued" && !job.stage ? "Waiting for its turn" : job.stage || "Starting";
  return (
    <div className="space-y-1.5" aria-label={`${job.title}: ${label}`}>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="truncate text-muted-foreground">
          {label}
          {pct !== null && running ? ` · ${unit}` : ""}
          {running && job.seconds_left !== null ? ` · ${timeLeft(job.seconds_left)}` : ""}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          {pct !== null && running && <span className="tabular-nums text-xs">{pct}%</span>}
          {onCancel && (
            <Button size="sm" variant="ghost" onClick={onCancel} aria-label="Cancel">
              <X className="h-4 w-4" /> Cancel
            </Button>
          )}
        </div>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${waiting ? "bg-amber-500/70" : "bg-primary"} ${
            pct === null || !running ? "animate-pulse w-1/3" : ""
          }`}
          style={pct === null || !running ? undefined : { width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function Notice({ tone, children }: { tone: "warn" | "info"; children: ReactNode }) {
  const warn = tone === "warn";
  return (
    <div
      className={`flex items-start gap-2 rounded-md border p-3 text-sm ${
        warn ? "border-amber-500/40 bg-amber-500/10" : "border-sky-500/30 bg-sky-500/5"
      }`}
    >
      {warn ? (
        <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
      ) : (
        <Info className="h-4 w-4 text-sky-500 shrink-0 mt-0.5" />
      )}
      <div>{children}</div>
    </div>
  );
}

function ModelRow({ model, inUse }: { model: VoiceModelChoice; inUse: boolean }) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{model.title}</span>
        <Badge variant="outline">{model.quality}</Badge>
        {model.recommended && <Badge>Recommended</Badge>}
        {model.installed && (
          <Badge variant="secondary">
            <Check className="h-3 w-3" /> {inUse ? "In use" : "Installed"}
          </Badge>
        )}
        {!model.installed && <span className="ml-auto text-xs text-muted-foreground">{gigabytes(model.size)}</span>}
      </div>
      <div className="mt-1 text-xs text-muted-foreground">{model.blurb}</div>
      <div className={`mt-1 text-xs ${FIT[model.fit].className}`}>{FIT[model.fit].label}</div>
    </>
  );
}

export default function VoiceSubtitlesPage() {
  const [status, setStatus] = useState<VoiceSubtitlesStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [chosenModel, setChosenModel] = useState<string | null>(null);
  const [choosingModel, setChoosingModel] = useState(false);
  const [search, setSearch] = useState("");
  const [review, setReview] = useState<{ mod: VoiceMod; language: string } | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await getVoiceSubtitles();
      setStatus(next);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  const busy = useMemo(
    () => !!status && (status.scanning || status.jobs.some((j) => ACTIVE_STATES.has(j.state))),
    [status],
  );
  useAdaptivePoll(refresh, { activeMs: 1500, idleMs: 15000, isActive: () => busy });

  const run = async (label: string, action: () => Promise<unknown>, success?: string) => {
    setPending(label);
    try {
      await action();
      if (success) toast.success(success);
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setPending(null);
    }
  };

  if (!status) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground gap-2">
        {loadError ? (
          <>
            <AlertTriangle className="h-5 w-5 text-amber-500" /> {loadError}
          </>
        ) : (
          <>
            <Loader2 className="h-5 w-5 animate-spin" /> Loading…
          </>
        )}
      </div>
    );
  }

  const nameOf = (code: string) => status.languages.find((l) => l.code === code)?.name ?? code;
  const language = status.language;
  const languageName = nameOf(language);
  const needsTranslation = language !== "en";
  const jobs = status.jobs;
  const activeJobs = jobs.filter((j) => ACTIVE_STATES.has(j.state));
  const installJobs = activeJobs.filter((j) => j.kind === "install");
  const recognitionJobs = installJobs.filter(isRecognitionJob);
  const modelJobs = installJobs.filter((j) => !isRecognitionJob(j));
  const makeJobFor = (key: string) =>
    activeJobs.find((j) => j.kind === "make" && j.target === key && j.language === language);
  const recentFinished = jobs
    .filter((j) => !ACTIVE_STATES.has(j.state) && j.state !== "cancelled")
    .slice(-3)
    .reverse();

  const translation = status.translation;
  const models = translation.models;
  const modelTitle = (id: string) => models.find((m) => m.id === id)?.title ?? id;
  // The backend lists the models best first.
  const modelRank = (id: string) => {
    const index = models.findIndex((m) => m.id === id);
    return index < 0 ? models.length : index;
  };
  const inUse = models.find((m) => m.id === translation.model && m.installed) ?? null;
  const selectedId = chosenModel ?? translation.model ?? translation.recommended;
  const selected = models.find((m) => m.id === selectedId) ?? models[0];
  const showModelList = !translation.ready || choosingModel || modelJobs.length > 0;

  const notReadyReason = !status.game_found
    ? "Set the Marvel Rivals folder in Settings first"
    : !status.downloads_folder
      ? "Set the mod downloads folder in Settings first"
      : !status.recognition.installed
        ? "Install speech recognition first"
        : needsTranslation && !translation.ready
          ? "Install a translation model first"
          : null;
  const ready = notReadyReason === null;

  const gpu = status.hardware.gpus.slice().sort((a, b) => b.vram_mb - a.vram_mb)[0];
  const machine = [
    gpu ? `${gpu.name} · ${Math.round(gpu.vram_mb / 1024)} GB` : "No graphics card the models can use",
    `${Math.round(status.hardware.ram_mb / 1024)} GB memory`,
  ].join(" · ");

  const needle = search.trim().toLowerCase();
  const shownMods = status.voice_mods.filter(
    (m) => !needle || m.hero_name.toLowerCase().includes(needle) || m.name.toLowerCase().includes(needle),
  );
  const heroes = new Map<string, VoiceMod[]>();
  for (const mod of shownMods) {
    const list = heroes.get(mod.hero_name) ?? [];
    list.push(mod);
    heroes.set(mod.hero_name, list);
  }
  const heroGroups = [...heroes.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  const toMake = status.voice_mods.filter(
    (m) => !m.skipped && m.subtitles[language]?.state !== "ready" && !makeJobFor(m.key),
  );

  const chooseFolder = async () => {
    try {
      const folder = await invoke<string>("select_folder_dialog", { defaultPath: status.folder });
      if (folder) {
        await run("folder", () => setVoiceSubtitlesSettings({ folder }), "Moved");
      }
    } catch (error) {
      if (error !== "Selection cancelled") toast.error(String(error));
    }
  };

  const toggle = async (mod: VoiceMod, on: boolean) => {
    const sub = mod.subtitles[language];
    if (!sub?.download_id) return;
    await run(`toggle-${mod.key}`, () => setActivePaks(sub.download_id as number, on ? [sub.pak] : []));
  };

  const make = (mod: VoiceMod) => run(`make-${mod.key}`, () => makeVoiceSubtitles(mod.key, language));
  const cancel = (job: VoiceJob) => run(`cancel-${job.id}`, () => cancelVoiceJob(job.id));

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1 max-w-2xl">
            <h2 className="text-xl font-semibold flex items-center gap-2">
              <Captions className="h-5 w-5" /> Voice Subtitles
            </h2>
            <p className="text-sm text-muted-foreground">
              A voice mod changes what a hero says, not the subtitle on screen. Here the words of a voice mod are
              heard and, if you like, translated, all on this computer. Each voice mod gets its own subtitle mod in
              your library, filed under its hero: switch it on together with the voice mod.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Languages className="h-4 w-4 text-muted-foreground" />
            <Select
              value={language}
              onValueChange={(value) =>
                run("language", () =>
                  setVoiceSubtitlesSettings({ language: value === status.game_language ? null : value }),
                )
              }
            >
              <SelectTrigger className="w-56" aria-label="Subtitle language">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {status.languages.map((l) => (
                  <SelectItem key={l.code} value={l.code}>
                    {l.name}
                    {l.code === status.game_language ? " (the game's)" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {!status.game_found && (
          <Notice tone="warn">
            Set the Marvel Rivals folder in Settings: the game's own subtitles are needed to match lines.
          </Notice>
        )}
        {status.game_found && !status.downloads_folder && (
          <Notice tone="warn">Set the mod downloads folder in Settings: subtitle mods are saved there.</Notice>
        )}
        {language !== status.game_language && (
          <Notice tone="info">
            The game is set to {nameOf(status.game_language)}. {languageName} subtitle mods show in it as well
            {language === "en" ? ": they are the voice mod's own words, untranslated" : ""}. If a voice mod has
            subtitles in both languages switched on, the game's language wins.
          </Notice>
        )}
        {status.game_running && activeJobs.some((j) => j.kind === "make") && (
          <Notice tone="info">
            Marvel Rivals is running. Making subtitles waits until it is closed, so the game keeps the graphics card
            to itself.
          </Notice>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <Card className="gap-4">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Mic className="h-4 w-4" /> 1. Speech recognition
                {status.recognition.installed && <Badge variant="secondary">Installed</Badge>}
              </CardTitle>
              <CardDescription>
                Hears what a voice mod says (Whisper). Needed for subtitles in any language.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {recognitionJobs.map((j) => (
                <JobProgress key={j.id} job={j} onCancel={() => cancel(j)} />
              ))}
              {!status.recognition.installed ? (
                recognitionJobs.length === 0 && (
                  <Button
                    onClick={() => run("recognition", () => installVoiceComponent("recognition"))}
                    disabled={!!pending}
                  >
                    Install ({gigabytes(status.recognition.size)})
                  </Button>
                )
              ) : (
                <div className="flex flex-wrap items-center justify-between gap-3">
                  {status.recognition.gpu.available ? (
                    <label className="flex items-center gap-2 text-sm">
                      <Switch
                        checked={status.recognition.gpu.on && status.recognition.gpu.installed}
                        disabled={!!pending || recognitionJobs.length > 0}
                        onCheckedChange={(on) =>
                          on
                            ? run("gpu", () => installVoiceComponent("gpu-recognition"))
                            : run("gpu", () => setVoiceSubtitlesSettings({ gpu_recognition: false }))
                        }
                        aria-label="Recognise on the graphics card"
                      />
                      Use the graphics card
                      {!status.recognition.gpu.installed && (
                        <span className="text-muted-foreground">(+{gigabytes(status.recognition.gpu.size)})</span>
                      )}
                    </label>
                  ) : (
                    <span className="text-sm text-muted-foreground">Runs on the processor.</span>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!!pending || activeJobs.length > 0}
                    onClick={() => run("remove-recognition", () => removeVoiceComponent("recognition"), "Removed")}
                  >
                    Remove
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="gap-4">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Languages className="h-4 w-4" /> 2. Translation
                {needsTranslation && translation.ready && <Badge variant="secondary">Installed</Badge>}
              </CardTitle>
              <CardDescription>
                {needsTranslation
                  ? `Translates into ${languageName} with a model that runs on this computer.`
                  : "Not needed: English subtitles are the words heard."}
              </CardDescription>
            </CardHeader>
            {needsTranslation && (
              <CardContent className="space-y-3">
                {!showModelList && inUse ? (
                  <>
                    <div className="rounded-md border p-3">
                      <ModelRow model={inUse} inUse />
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setChosenModel(inUse.id);
                          setChoosingModel(true);
                        }}
                      >
                        Change model
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={!!pending || activeJobs.length > 0}
                        onClick={() => run("remove-model", () => removeVoiceComponent(inUse.id), "Removed")}
                      >
                        Remove
                      </Button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="space-y-2" role="radiogroup" aria-label="Translation model">
                      {models.map((m) => {
                        const active = m.id === selected?.id;
                        return (
                          <button
                            key={m.id}
                            type="button"
                            role="radio"
                            aria-checked={active}
                            onClick={() => setChosenModel(m.id)}
                            className={`w-full text-left rounded-md border p-3 transition-colors ${
                              active ? "border-primary bg-primary/5" : "border-border hover:bg-accent/40"
                            }`}
                          >
                            <ModelRow model={m} inUse={m.id === translation.model} />
                          </button>
                        );
                      })}
                    </div>
                    {modelJobs.map((j) => (
                      <JobProgress key={j.id} job={j} onCancel={() => cancel(j)} />
                    ))}
                    {selected && modelJobs.length === 0 && (
                      <div className="flex flex-wrap gap-2">
                        {!selected.installed ? (
                          <Button
                            disabled={!!pending || selected.fit === "no"}
                            onClick={() =>
                              run("install-model", async () => {
                                await installVoiceComponent(selected.id);
                                setChoosingModel(false);
                              })
                            }
                          >
                            Install {selected.title} ({gigabytes(selected.size)})
                          </Button>
                        ) : selected.id !== translation.model ? (
                          <Button
                            disabled={!!pending}
                            onClick={() =>
                              run("use-model", async () => {
                                await setVoiceSubtitlesSettings({ model: selected.id });
                                setChoosingModel(false);
                              })
                            }
                          >
                            Use {selected.title}
                          </Button>
                        ) : null}
                        {selected.installed && (
                          <Button
                            variant="ghost"
                            disabled={!!pending || activeJobs.length > 0}
                            onClick={() => run("remove-model", () => removeVoiceComponent(selected.id), "Removed")}
                          >
                            Remove
                          </Button>
                        )}
                        {choosingModel && translation.ready && (
                          <Button variant="ghost" onClick={() => setChoosingModel(false)}>
                            Done
                          </Button>
                        )}
                      </div>
                    )}
                  </>
                )}
              </CardContent>
            )}
          </Card>
        </div>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-muted-foreground">
          <span className="flex items-center gap-2">
            <Cpu className="h-4 w-4" /> {machine}
          </span>
          <span className="flex items-center gap-2 min-w-0">
            <HardDrive className="h-4 w-4 shrink-0" />
            <span className="truncate" title={status.folder}>
              {status.folder}
            </span>
            {status.free_bytes !== null && <span className="shrink-0">({gigabytes(status.free_bytes)} free)</span>}
            <Button variant="ghost" size="sm" onClick={chooseFolder} disabled={!!pending || activeJobs.length > 0}>
              <FolderOpen className="h-4 w-4" /> Change
            </Button>
          </span>
        </div>

        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-medium">
              3. Voice mods <span className="text-muted-foreground">({status.voice_mods.length})</span>
            </h3>
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              {status.scanning && (
                <span className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" /> {status.scan_note || "Looking for voice mods…"}
                </span>
              )}
              {status.voice_mods.length >= SEARCH_FROM && (
                <div className="relative">
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    className="h-8 w-48 pl-8"
                    placeholder="Hero or mod"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    aria-label="Search voice mods"
                  />
                </div>
              )}
              {toMake.length > 1 && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!ready || !!pending}
                  title={notReadyReason ?? undefined}
                  onClick={() => run("make-all", () => makeAllVoiceSubtitles(language))}
                >
                  <ListChecks className="h-4 w-4" /> Make all ({toMake.length})
                </Button>
              )}
              <Button variant="outline" size="sm" onClick={() => run("rescan", rescanVoiceMods)} disabled={status.scanning}>
                <RefreshCw className="h-4 w-4" /> Look again
              </Button>
            </div>
          </div>

          {status.combined?.waiting && (
            <div className="text-sm text-amber-500">The subtitle file is updated once the game is closed.</div>
          )}
          {status.combined?.error && (
            <div className="text-sm text-red-500">Could not update the subtitle file: {status.combined.error}</div>
          )}

          {recentFinished.length > 0 && (
            <div className="space-y-1">
              {recentFinished.map((j) => (
                <div
                  key={j.id}
                  className={`text-sm flex items-center gap-2 ${j.state === "failed" ? "text-red-500" : "text-muted-foreground"}`}
                >
                  {j.state === "failed" ? (
                    <AlertTriangle className="h-4 w-4 shrink-0" />
                  ) : (
                    <Check className="h-4 w-4 text-emerald-500 shrink-0" />
                  )}
                  <span className="truncate">
                    {j.title}
                    {j.state === "failed"
                      ? `: ${j.error}`
                      : j.kind === "make"
                        ? `: ${nameOf(j.language ?? "en")} subtitles made`
                        : ": installed"}
                  </span>
                </div>
              ))}
            </div>
          )}

          {status.voice_mods.length === 0 && !status.scanning && (
            <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
              No voice mods found, neither switched on nor in your library. A voice mod is one that replaces a hero's
              voice lines.
            </div>
          )}
          {status.voice_mods.length > 0 && shownMods.length === 0 && (
            <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
              No voice mod matches “{search}”.
            </div>
          )}

          {heroGroups.map(([hero, mods]) => (
            <Card key={hero} className="gap-0 py-0">
              <div className="px-4 py-2 border-b text-sm font-medium flex items-center justify-between">
                <span>{hero}</span>
                {mods.length > 1 && <span className="text-xs text-muted-foreground">{mods.length} voice mods</span>}
              </div>
              {mods.map((mod) => {
                const sub = mod.subtitles[language];
                const job = makeJobFor(mod.key);
                const counts = sub?.counts;
                const otherModels =
                  needsTranslation && translation.ready && sub?.state === "ready"
                    ? (sub.models ?? []).filter((m) => m !== translation.model)
                    : [];
                // Worth doing again only with a better model than the ones that made it.
                const betterNow =
                  otherModels.length > 0 &&
                  modelRank(translation.model ?? "") < Math.min(...otherModels.map(modelRank));
                return (
                  <div key={mod.key} className="px-4 py-3 border-b last:border-b-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm" title={mod.name}>
                          {mod.name.replace(/_\d+_P\.pak$/i, "")}
                        </div>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1">
                          {mod.installed.length > 0 ? (
                            <Badge variant="secondary">Voice mod on</Badge>
                          ) : (
                            <Badge variant="outline">In library</Badge>
                          )}
                          {sub?.state === "ready" && counts && (
                            <span className="text-xs text-muted-foreground">
                              {counts.subtitled} lines · {counts.silenced} silenced
                              {counts.kept > 0 ? ` · ${counts.kept} keep the game's` : ""}
                            </span>
                          )}
                          {sub?.state === "partial" && counts && (
                            <span className="text-xs text-amber-500">{counts.missing} lines still to translate</span>
                          )}
                          {otherModels.length > 0 && (
                            <span className="text-xs text-muted-foreground">
                              Translated by {otherModels.map(modelTitle).join(", ")}
                            </span>
                          )}
                        </div>
                      </div>
                      {mod.skipped ? (
                        <span className="text-xs text-muted-foreground">Not made for this hero</span>
                      ) : job ? null : sub?.state === "ready" ? (
                        <div className="flex flex-wrap items-center gap-2">
                          {betterNow && (
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={!ready || !!pending}
                              title={`Translate again with ${modelTitle(translation.model ?? "")}; your own edits stay`}
                              onClick={() => make(mod)}
                            >
                              <RotateCcw className="h-4 w-4" /> Translate again
                            </Button>
                          )}
                          <Button size="sm" variant="ghost" onClick={() => setReview({ mod, language })}>
                            <Pencil className="h-4 w-4" /> Review
                          </Button>
                          <label
                            className="flex items-center gap-2 text-sm"
                            title={sub.download_id ? undefined : "Being added to the library…"}
                          >
                            <Switch
                              checked={sub.active}
                              disabled={!sub.download_id || pending === `toggle-${mod.key}`}
                              onCheckedChange={(on) => toggle(mod, on)}
                              aria-label="Subtitle mod on"
                            />
                            Subtitles {sub.active ? "on" : "off"}
                          </label>
                        </div>
                      ) : (
                        <Button
                          size="sm"
                          disabled={!ready || !!pending}
                          title={notReadyReason ?? undefined}
                          onClick={() => make(mod)}
                        >
                          <Play className="h-4 w-4" /> {sub?.state === "partial" ? "Continue" : "Make subtitles"}
                        </Button>
                      )}
                    </div>
                    {job && <JobProgress job={job} onCancel={() => cancel(job)} />}
                  </div>
                );
              })}
            </Card>
          ))}
        </div>
      </div>

      {review && (
        <VoiceLinesDialog
          mod={review.mod}
          language={review.language}
          languageName={nameOf(review.language)}
          onClose={() => {
            setReview(null);
            void refresh();
          }}
        />
      )}
    </div>
  );
}
