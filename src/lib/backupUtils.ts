/**
 * Mod Backup System – data model, localStorage helpers, and backup I/O logic.
 */

// ─── Data Model ─────────────────────────────────────────────────────────────

/** Represents a single mod entry stored inside a backup file. */
export interface ModBackupEntry {
  modId: string;
  backendModId: number | null;
  name: string;
  author: string;
  version: string;
  isActive: boolean;
  images: string[];
  sourceDownloadIds: number[];
  sourceFileIds: number[];
  activePaks?: string[];
  /** User-created custom tags for this mod (optional, absent in older backups). */
  customTags?: string[];
  /** Custom description for this mod (optional). */
  description?: string | null;
  /** Custom images uploaded for this mod (optional). */
  customImages?: { data: string; filename?: string; mimeType?: string }[];
  /** Custom Author Metadata (optional) */
  customAuthorId?: number | null;
  customAuthorName?: string | null;
  customAuthorType?: string | null;
  customAuthorAvatar?: string | null;
}

/** The full backup object saved to disk as JSON. */
export interface ModBackup {
  id: string;
  name: string;
  createdAt: string;        // ISO timestamp
  totalMods: number;
  activeMods: number;
  mods: ModBackupEntry[];
}

/** Lightweight metadata stored in localStorage (without the full mod list). */
export interface BackupMeta {
  id: string;
  name: string;
  createdAt: string;
  filePath: string;         // absolute path to the .json file on disk
  totalMods: number;
  activeMods: number;
}

// ─── localStorage ────────────────────────────────────────────────────────────

const LS_KEY = "rivalnxt:backups";

export function loadBackupMetas(): BackupMeta[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as BackupMeta[];
  } catch {
    return [];
  }
}

function saveBackupMetas(metas: BackupMeta[]): void {
  localStorage.setItem(LS_KEY, JSON.stringify(metas));
}

export function addBackupMeta(meta: BackupMeta): void {
  const metas = loadBackupMetas();
  // Newest first
  metas.unshift(meta);
  saveBackupMetas(metas);
}

export function removeBackupMeta(id: string): void {
  const metas = loadBackupMetas().filter((m) => m.id !== id);
  saveBackupMetas(metas);
}

// ─── Snapshot builder ────────────────────────────────────────────────────────

/**
 * Builds a ModBackup snapshot from the current UI mod list.
 * Captures all installed mods with their active/inactive state.
 */
export function buildBackupFromMods(mods: any[], name: string): ModBackup {
  const id = `backup_${Date.now()}`;
  const createdAt = new Date().toISOString();

  const entries: ModBackupEntry[] = mods
    .filter((m) => m.isInstalled)
    .map((m) => ({
      modId: String(m.id),
      backendModId: m.backendModId ?? null,
      name: m.name || "Unknown Mod",
      author: m.author || "",
      version: m.version || "",
      isActive: Boolean(m.isActive),
      images: Array.isArray(m.images) ? m.images.slice(0, 1) : [],
      sourceDownloadIds: Array.isArray(m.sourceDownloadIds)
        ? m.sourceDownloadIds
        : [],
      sourceFileIds: Array.isArray(m.sourceFileIds) ? m.sourceFileIds : [],
      activePaks: Array.isArray(m.defaultActivePaks) ? m.defaultActivePaks : [],
      customAuthorId: m.customAuthorId ?? null,
      customAuthorName: m.customAuthorName ?? null,
      customAuthorType: m.customAuthorType ?? null,
      customAuthorAvatar: m.customAuthorAvatar ?? null,
    }));

  return {
    id,
    name,
    createdAt,
    totalMods: entries.length,
    activeMods: entries.filter((e) => e.isActive).length,
    mods: entries,
  };
}

/**
 * Generates a friendly datetime name for a new backup.
 * Example: "2026-05-16 19:18"
 */
export function generateBackupName(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(
    now.getDate()
  )} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

// ─── Restore logic ───────────────────────────────────────────────────────────

export interface RestoreResult {
  /** Mods that were toggled (active state changed). */
  toggled: string[];
  /** Mod names that are in the backup but not currently installed. */
  missing: string[];
}

/**
 * Compares a backup against the current installed mods list and returns
 * which mods need toggling and which are missing.
 *
 * Does NOT call onToggleMod — caller is responsible for applying the changes.
 */
export function computeRestoreDiff(
  backup: ModBackup,
  installedMods: any[]
): { toEnable: any[]; toDisable: any[]; missing: string[] } {
  const toEnable: any[] = [];
  const toDisable: any[] = [];
  const missing: string[] = [];

  for (const entry of backup.mods) {
    // Match by backendModId first, then sourceDownloadIds, then modId
    const match = installedMods.find((m) => {
      if (entry.backendModId != null && m.backendModId != null) {
        return m.backendModId === entry.backendModId;
      }
      if (
        entry.sourceDownloadIds.length > 0 &&
        Array.isArray(m.sourceDownloadIds)
      ) {
        return entry.sourceDownloadIds.some((id) =>
          m.sourceDownloadIds.includes(id)
        );
      }
      return String(m.id) === entry.modId;
    });

    if (!match) {
      missing.push(entry.name);
      continue;
    }

    const currentlyActive = Boolean(match.isActive);
    if (entry.isActive && !currentlyActive) {
      toEnable.push(match);
    } else if (!entry.isActive && currentlyActive) {
      toDisable.push(match);
    }
  }

  return { toEnable, toDisable, missing };
}

// ─── Backend-backed backups (v2) ─────────────────────────────────────────────
// v1 backups were a JSON projection of mod metadata written by the frontend,
// indexed in localStorage. v2 backups are zip archives produced by the backend
// containing the real mods.db plus settings.json, and the filesystem is the
// index. Both must remain readable: users have v1 files on disk already.

/** Manifest of a v2 (backend) backup, as returned by GET /api/backup/list. */
export interface ServerBackupInfo {
  name: string;
  path: string;
  created_at: string | null;
  size_bytes: number;
  manifest_version: number | null;
  total_mods: number | null;
  active_mods: number | null;
  kind?: string;
  description?: string;
}

/** Discriminated view over either backup generation, for a single UI list. */
export interface UnifiedBackup {
  id: string;
  name: string;
  createdAt: string;
  /** v1: absolute path to the .json file. v2: absolute path to the .zip. */
  filePath: string;
  totalMods: number;
  activeMods: number;
  generation: 1 | 2;
  /** Only v2 archives can be restored through the backend endpoint. */
  restorableViaApi: boolean;
  /** Why it exists: "manual", "pre-restore", "pre-compact". */
  kind: string;
  /** Sentence explaining the archive, shown under its name. */
  description: string;
  sizeBytes: number;
}

/** Adapt a legacy localStorage entry into the unified shape. Lossless: every
 * field of BackupMeta is represented. */
export function fromLegacyMeta(meta: BackupMeta): UnifiedBackup {
  return {
    id: meta.id,
    name: meta.name,
    createdAt: meta.createdAt,
    filePath: meta.filePath,
    totalMods: meta.totalMods,
    activeMods: meta.activeMods,
    generation: 1,
    restorableViaApi: false,
    kind: "manual",
    description: "Portable .json export you saved. Mod states and tags only.",
    sizeBytes: 0,
  };
}

/** Adapt a backend manifest into the unified shape. */
export function fromServerBackup(info: ServerBackupInfo): UnifiedBackup {
  return {
    id: info.path,
    name: info.name,
    createdAt: info.created_at ?? "",
    filePath: info.path,
    totalMods: info.total_mods ?? 0,
    activeMods: info.active_mods ?? 0,
    generation: 2,
    restorableViaApi: true,
    kind: info.kind ?? "manual",
    description: info.description ?? "",
    sizeBytes: info.size_bytes ?? 0,
  };
}

/**
 * Merge both generations into one newest-first list.
 *
 * A v1 entry whose file path matches a v2 archive is dropped in favour of the
 * v2 record, so migrated backups do not appear twice.
 */
export function mergeBackupSources(
  legacy: BackupMeta[],
  server: ServerBackupInfo[],
): UnifiedBackup[] {
  const serverEntries = server.map(fromServerBackup);
  const serverPaths = new Set(serverEntries.map((e) => e.filePath));
  const legacyEntries = legacy
    .filter((m) => !serverPaths.has(m.filePath))
    .map(fromLegacyMeta);

  return [...serverEntries, ...legacyEntries].sort((a, b) =>
    (b.createdAt || "").localeCompare(a.createdAt || ""),
  );
}

// ─── JSON export size limits ─────────────────────────────────────────────────
// A v1 export embeds every custom image as base64 inside one JSON string.
// /api/mods/{id}/images returns images at FULL resolution (unlike the list
// preview endpoint, which downscales to 400px), so a library with a few hundred
// mods produced a string past V8's maximum length and JSON.stringify threw
// "Invalid string length" — the export failed outright, with no file written.
//
// Images are therefore embedded on a budget. Anything beyond it is dropped from
// the JSON: the archive (v2 zip) already carries mods.db, which holds every
// image at full fidelity, so nothing is actually lost — only the portability of
// this one JSON file to a different machine.

/** Skip any single image larger than this (base64 characters). */
export const MAX_EMBEDDED_IMAGE_CHARS = 2 * 1024 * 1024;

/** Stop embedding once the running total passes this (base64 characters). */
export const MAX_EMBEDDED_IMAGE_BUDGET_CHARS = 48 * 1024 * 1024;

/** Tracks how much image payload a single export has spent. */
export class ImageBudget {
  private spent = 0;
  private skipped = 0;

  constructor(
    private readonly perImageLimit = MAX_EMBEDDED_IMAGE_CHARS,
    private readonly totalLimit = MAX_EMBEDDED_IMAGE_BUDGET_CHARS,
  ) {}

  /** Returns the images that fit, charging the budget for each one kept. */
  take(
    images: { data: string; filename?: string; mimeType?: string }[],
  ): { data: string; filename?: string; mimeType?: string }[] {
    const kept: { data: string; filename?: string; mimeType?: string }[] = [];
    for (const img of images) {
      const size = img.data?.length ?? 0;
      if (size === 0) continue;
      if (size > this.perImageLimit || this.spent + size > this.totalLimit) {
        this.skipped++;
        continue;
      }
      this.spent += size;
      kept.push(img);
    }
    return kept;
  }

  get skippedCount(): number {
    return this.skipped;
  }

  get spentChars(): number {
    return this.spent;
  }
}

/**
 * Serialize a backup, degrading rather than failing.
 *
 * Even with the budget applied, JSON.stringify can still throw a RangeError on
 * a pathological library. Dropping the embedded images is always preferable to
 * handing the user an error and no backup at all, so that is the fallback.
 *
 * Note the missing indent argument: pretty-printing a 177-mod snapshot adds
 * megabytes of whitespace to a string that is already near the engine limit.
 */
export function serializeBackup(backup: ModBackup): {
  json: string;
  droppedImages: boolean;
} {
  try {
    return { json: JSON.stringify(backup), droppedImages: false };
  } catch (err) {
    if (!(err instanceof RangeError)) throw err;
    const stripped: ModBackup = {
      ...backup,
      mods: backup.mods.map(({ customImages: _customImages, ...rest }) => rest),
    };
    return { json: JSON.stringify(stripped), droppedImages: true };
  }
}

// ─── Loadouts ────────────────────────────────────────────────────────────────
// A loadout is the answer to "turn everything off, then put it all back exactly
// as it was". It is deliberately NOT a backup: it stores only which pak files
// were active per download — no images, no tags, no descriptions. That keeps it
// a few kilobytes, so it fits in localStorage and can be captured on every
// Disable All without the user thinking about it.
//
// Mod artwork is unaffected by any of this. Images live in mods.db keyed by mod,
// and activating/deactivating only moves .pak files in and out of the game's
// ~mods folder, so thumbnails survive a disable-all untouched.

const LOADOUT_LS_KEY = "rivalnxt:loadouts";

/** How many loadouts to retain; oldest are pruned past this. */
const MAX_LOADOUTS = 20;

/** The id used for the snapshot taken automatically before a Disable All. */
export const AUTO_LOADOUT_ID = "auto:last-disable-all";

export interface Loadout {
  id: string;
  name: string;
  createdAt: string;
  /** downloadId (as a string key) -> exact active pak paths at capture time. */
  entries: Record<string, string[]>;
  /** Number of downloads that had at least one active pak. */
  activeDownloads: number;
  /** Total active pak files across all downloads. */
  activePaks: number;
}

/** Shape this needs from ApiDownload — kept structural so tests need no fixtures. */
export interface LoadoutSourceDownload {
  id: number | string;
  active_paks?: string[] | null;
}

/**
 * Capture the currently-active pak selection.
 *
 * Built from the backend download list rather than the UI mod list because
 * active_paks there is reconciled against the real ~mods folder, so it reflects
 * what the game will actually load.
 */
export function buildLoadout(
  downloads: LoadoutSourceDownload[],
  name: string,
  id?: string,
): Loadout {
  const entries: Record<string, string[]> = {};
  let activePaks = 0;

  for (const dl of downloads) {
    const paks = Array.isArray(dl.active_paks) ? dl.active_paks.filter(Boolean) : [];
    if (paks.length === 0) continue;
    entries[String(dl.id)] = paks;
    activePaks += paks.length;
  }

  return {
    id: id ?? `loadout_${Date.now()}`,
    name,
    createdAt: new Date().toISOString(),
    entries,
    activeDownloads: Object.keys(entries).length,
    activePaks,
  };
}

export function loadLoadouts(): Loadout[] {
  try {
    const raw = localStorage.getItem(LOADOUT_LS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as Loadout[]) : [];
  } catch {
    return [];
  }
}

function saveLoadouts(loadouts: Loadout[]): void {
  localStorage.setItem(LOADOUT_LS_KEY, JSON.stringify(loadouts.slice(0, MAX_LOADOUTS)));
}

/** Insert newest-first, replacing any existing loadout with the same id. */
export function addLoadout(loadout: Loadout): void {
  const rest = loadLoadouts().filter((l) => l.id !== loadout.id);
  saveLoadouts([loadout, ...rest]);
}

export function removeLoadout(id: string): void {
  saveLoadouts(loadLoadouts().filter((l) => l.id !== id));
}

export function getLoadout(id: string): Loadout | null {
  return loadLoadouts().find((l) => l.id === id) ?? null;
}

// ─── Unified restore list ────────────────────────────────────────────────────
// Backups and loadouts were presented as two separate panels with two separate
// Restore buttons, and the difference between them was never stated anywhere in
// the UI. Both answer the same user question -- "put my mods back the way they
// were" -- so they belong in one list, ordered by when they were taken, with the
// difference shown as a label on each row rather than as a wall between them.

export type RestorePointKind = "full" | "loadout" | "export";

export interface RestorePoint {
  id: string;
  kind: RestorePointKind;
  /** Sort key and what the row displays. Empty when a manifest lacked one. */
  createdAt: string;
  name: string;
  /** What restoring this actually brings back. */
  summary: string;
  /** Set for kind "full" and "export". */
  backup?: UnifiedBackup;
  /** Set for kind "loadout". */
  loadout?: Loadout;
}

/** How much of the library each kind of restore point covers. */
export const RESTORE_POINT_SCOPE: Record<RestorePointKind, string> = {
  full: "Whole library — mods, artwork, tags and which mods were on.",
  export: "Portable file — which mods were on, plus tags. No artwork.",
  loadout: "Which mods were on. Nothing else is touched.",
};

/**
 * One newest-first list of everything that can be restored.
 *
 * The remembered loadout is included only when it has something in it: an empty
 * one would offer a Restore that silently disables every mod.
 */
export function buildRestorePoints(
  backups: UnifiedBackup[],
  loadout: Loadout | null,
): RestorePoint[] {
  const points: RestorePoint[] = backups.map((backup) => ({
    id: backup.id,
    kind: backup.generation === 2 ? "full" : "export",
    createdAt: backup.createdAt,
    name: backup.name,
    summary:
      backup.totalMods > 0
        ? `${backup.totalMods} mods (${backup.activeMods} active)`
        : backup.description,
    backup,
  }));

  if (loadout && loadout.activeDownloads > 0) {
    points.push({
      id: loadout.id,
      kind: "loadout",
      createdAt: loadout.createdAt,
      name: loadout.name || "Before Disable All",
      summary: `${loadout.activeDownloads} mods · ${loadout.activePaks} pak file${
        loadout.activePaks === 1 ? "" : "s"
      }`,
      loadout,
    });
  }

  return points.sort((a, b) => (b.createdAt || "").localeCompare(a.createdAt || ""));
}

/**
 * Work out the per-download calls needed to make the live state match a loadout.
 *
 * Every download that is currently active but absent from the loadout gets an
 * explicit empty selection, otherwise restoring a smaller loadout would leave
 * strays enabled.
 */
export function computeLoadoutPlan(
  loadout: Loadout,
  downloads: LoadoutSourceDownload[],
): { downloadId: number; paks: string[] }[] {
  // Downloads recorded in the loadout that the list no longer reports are
  // ignored rather than guessed at — the mod may have been deleted since.
  const plan: { downloadId: number; paks: string[] }[] = [];

  for (const dl of downloads) {
    const target = loadout.entries[String(dl.id)] ?? [];
    const current = Array.isArray(dl.active_paks) ? dl.active_paks.filter(Boolean) : [];
    const same =
      target.length === current.length && target.every((p) => current.includes(p));
    if (!same) plan.push({ downloadId: Number(dl.id), paks: target });
  }

  return plan;
}
