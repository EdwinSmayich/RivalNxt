import { useState, useEffect, useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import {
  Archive,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  FolderOpen,
  Download,
  Power,
  ShieldCheck,
  Bookmark,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import {
  buildBackupFromMods,
  generateBackupName,
  addBackupMeta,
  computeRestoreDiff,
  serializeBackup,
  ImageBudget,
  getLoadout,
  loadBackupMetas,
  mergeBackupSources,
  buildRestorePoints,
  removeLoadout,
  RESTORE_POINT_SCOPE,
  AUTO_LOADOUT_ID,
  type ModBackup,
  type BackupMeta,
  type Loadout,
  type RestorePoint,
  type UnifiedBackup,
} from "../lib/backupUtils";
import {
  deletePreset,
  disableAllRemembering,
  findActivePreset,
  listPresets,
  restoreLoadout,
  savePreset,
} from "../lib/loadoutActions";
import {
  invokeSaveFileDialog,
  invokeSaveTextFile,
  invokeOpenFileDialog,
  invokeReadTextFile,
} from "../lib/tauri-utils";
import { setActivePaks, scanActive, refreshConflicts, getLocalDownload, getModCustomTags, addModCustomTag, getModDetails, fetchModImages, updateModDetails, uploadModImagesBase64, createBackup, restoreBackup, listServerBackups, deleteBackup, listDownloads } from "../lib/api";

interface BackupModalProps {
  open: boolean;
  onClose: () => void;
  mods: any[];
  onToggleMod: (modId: string) => void;
  onBackupCreated?: () => void;
  /** Called after a restore is applied — use this to refresh the mod list from the backend. */
  onBackupRestored?: () => void;
}

type ModalView = "home" | "creating" | "created" | "restoring" | "restored" | "archive";

/** Absolute date plus a relative hint — "date unknown" was never useful. */
function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "date unknown";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "date unknown";

  const minutes = Math.round((Date.now() - when.getTime()) / 60000);
  let relative: string;
  if (minutes < 1) relative = "just now";
  else if (minutes < 60) relative = `${minutes} min ago`;
  else if (minutes < 60 * 24) relative = `${Math.round(minutes / 60)} h ago`;
  else relative = `${Math.round(minutes / 1440)} d ago`;

  return `${when.toLocaleString()} · ${relative}`;
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes < 1024) return `${bytes || 0} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

interface RestorePreview {
  backup: ModBackup;
  filePath: string;
  toEnable: any[];
  toDisable: any[];
  missing: string[];
}

export function BackupModal({
  open,
  onClose,
  mods,
  onBackupCreated,
  onBackupRestored,
}: BackupModalProps) {
  const [view, setView] = useState<ModalView>("home");
  const [isWorking, setIsWorking] = useState(false);
  const [creatingStep, setCreatingStep] = useState<"gathering" | "saving">("gathering");
  const [restorePreview, setRestorePreview] = useState<RestorePreview | null>(
    null
  );
  const [lastSavedMeta, setLastSavedMeta] = useState<BackupMeta | null>(null);
  const [savedLoadout, setSavedLoadout] = useState<Loadout | null>(null);
  /** Path of a v2 (.zip) archive awaiting confirmation, restored by the backend. */
  const [archivePath, setArchivePath] = useState<string | null>(null);
  const [presets, setPresets] = useState<Loadout[]>([]);
  const [presetName, setPresetName] = useState("");
  const [activePresetId, setActivePresetId] = useState<string | null>(null);
  /** Archives on disk plus legacy localStorage entries, newest first. */
  const [knownBackups, setKnownBackups] = useState<UnifiedBackup[]>([]);
  const [loadingBackups, setLoadingBackups] = useState(false);
  /** Folder the archives live in, shown so they can be found outside the app. */
  const [backupsFolder, setBackupsFolder] = useState<string | null>(null);

  // Reset to home when modal opens
  useEffect(() => {
    if (open) {
      setView("home");
      setRestorePreview(null);
      setLastSavedMeta(null);
      setArchivePath(null);
      setPresetName("");
      const saved = listPresets();
      setPresets(saved);
      setSavedLoadout(getLoadout(AUTO_LOADOUT_ID));
      void refreshBackupList();
      // Which preset is loaded right now, so the list can say so.
      void listDownloads()
        .then((dls) => setActivePresetId(findActivePreset(dls, saved)?.id ?? null))
        .catch(() => setActivePresetId(null));
    }
  }, [open]);

  // The filesystem is the index for v2 archives; localStorage still holds the
  // legacy v1 entries. Merging both means a Full Snapshot no longer has to be
  // hunted down with a file dialog.
  const refreshBackupList = async () => {
    setLoadingBackups(true);
    try {
      const server = await listServerBackups();
      setKnownBackups(mergeBackupSources(loadBackupMetas(), server));
      // Derived from an archive path rather than asked for separately: the
      // backend already tells us where it put them.
      const first = server.find((b) => b.path);
      if (first) {
        const sep = first.path.includes("\\") ? "\\" : "/";
        setBackupsFolder(first.path.slice(0, first.path.lastIndexOf(sep)));
      }
    } catch (err) {
      console.warn("[BackupModal] Could not list backups", err);
      setKnownBackups(mergeBackupSources(loadBackupMetas(), []));
    } finally {
      setLoadingBackups(false);
    }
  };

  const installedMods = mods.filter((m) => m.isInstalled);
  const activeMods = installedMods.filter((m) => m.isActive);

  // One list, newest first. "Restore latest" is simply its first entry, which is
  // what people reach for when they have not been tracking which save is which.
  const restorePoints = useMemo(
    () => buildRestorePoints(knownBackups, savedLoadout),
    [knownBackups, savedLoadout],
  );
  const latestRestorePoint = restorePoints[0] ?? null;

  // ── Create backup ────────────────────────────────────────────────────────
  const handleCreateBackup = async () => {
    setIsWorking(true);
    setCreatingStep("gathering");
    setView("creating");
    try {
      const name = generateBackupName();
      // Build initial backup snapshot (active state + pak selection)
      const backup = buildBackupFromMods(mods, name);

      // Annotate each entry with the mod's custom tags (best-effort, non-blocking).
      //
      // Images are charged against a shared budget. Embedding every custom image
      // at full resolution is what produced "Invalid string length": the images
      // endpoint returns originals, and a few hundred mods of them exceed the
      // maximum length of a single JavaScript string, so JSON.stringify threw and
      // the user got no backup at all. The budget is shared across mods, so it
      // must be applied sequentially rather than inside the parallel map.
      const budget = new ImageBudget();
      const pendingImages: { entry: (typeof backup.mods)[number]; images: { data: string; filename?: string; mimeType?: string }[] }[] = [];

      await Promise.all(
        backup.mods.map(async (entry) => {
          try {
            // effectiveModId mirrors ModModal's logic: Nexus modId or -(first downloadId)
            const modId =
              entry.backendModId != null
                ? entry.backendModId
                : entry.sourceDownloadIds.length > 0
                  ? -entry.sourceDownloadIds[0]
                  : null;
            if (modId == null) return;

            // Fetch custom tags
            const tags = await getModCustomTags(modId);
            if (tags.length > 0) {
              entry.customTags = tags.map((t) => t.tag);
            }

            // Fetch description
            const details = await getModDetails(modId);
            if (details.mod?.description_bbcode || details.mod?.description) {
              entry.description = details.mod.description_bbcode || details.mod.description;
            }

            // Fetch custom images
            const images = await fetchModImages(modId);
            const customImgs = images
              .filter((img) => img.source === "custom")
              .map((img) => ({
                data: img.data || "",
                filename: img.filename,
                mimeType: img.mimeType,
              }))
              .filter((img) => img.data);
            if (customImgs.length > 0) {
              pendingImages.push({ entry, images: customImgs });
            }
          } catch {
            // Ignore per-mod failures — tags are best-effort
          }
        })
      );

      for (const { entry, images } of pendingImages) {
        const kept = budget.take(images);
        if (kept.length > 0) entry.customImages = kept;
      }

      const defaultFileName = `rivalnxt-backup-${name
        .replace(/[: ]/g, "-")
        .replace(/--+/g, "-")}.json`;

      setCreatingStep("saving");
      const path = await invokeSaveFileDialog(defaultFileName, ["json"]);
      if (!path) {
        // User cancelled
        setView("home");
        return;
      }

      const { json, droppedImages } = serializeBackup(backup);
      await invokeSaveTextFile(path, json);

      const omitted = budget.skippedCount;
      if (droppedImages) {
        toast.warning("Images left out of this .json export", {
          description: "Use Full Snapshot to capture artwork.",
          duration: 6000,
        });
      } else if (omitted > 0) {
        toast.info(`${omitted} oversized image${omitted > 1 ? "s" : ""} skipped`, {
          description: "Your mods keep their artwork — only this .json copy omits them.",
          duration: 6000,
        });
      }

      const meta: BackupMeta = {
        id: backup.id,
        name: backup.name,
        createdAt: backup.createdAt,
        filePath: path,
        totalMods: backup.totalMods,
        activeMods: backup.activeMods,
      };
      addBackupMeta(meta);
      setLastSavedMeta(meta);
      setView("created");
      toast.success(`Backup saved: ${name}`, {
        description: `${backup.totalMods} mods snapshotted (${backup.activeMods} active)`,
      });
      if (onBackupCreated) {
        onBackupCreated();
      }
    } catch (err: any) {
      toast.error(`Failed to save backup: ${err?.message ?? String(err)}`);
      setView("home");
    } finally {
      setIsWorking(false);
    }
  };

  // ── Full snapshot (backend zip) ───────────────────────────────────────────
  // The backend snapshots mods.db itself via SQLite's online backup API, so
  // artwork, tags, descriptions and the active pak selection are all captured at
  // full fidelity. Nothing is serialized in the webview, which is why this path
  // cannot hit the string-length ceiling that the .json export has to budget for.
  const handleFullSnapshot = async () => {
    setIsWorking(true);
    setCreatingStep("saving");
    setView("creating");
    try {
      const name = generateBackupName();
      const result = await createBackup(name);

      const meta: BackupMeta = {
        id: result.path,
        name: result.name || name,
        createdAt: result.created_at || new Date().toISOString(),
        filePath: result.path,
        totalMods: result.total_mods ?? installedMods.length,
        activeMods: result.active_mods ?? activeMods.length,
      };
      setLastSavedMeta(meta);
      setView("created");

      const rotated = result.pruned?.length ?? 0;
      toast.success(`Full snapshot saved: ${meta.name}`, {
        description:
          `${meta.totalMods} mods (${meta.activeMods} active) · ${formatBytes(result.size_bytes)}` +
          (rotated > 0 ? ` · ${rotated} old backup${rotated === 1 ? "" : "s"} rotated out` : ""),
      });
      onBackupCreated?.();
      void refreshBackupList();
    } catch (err: any) {
      toast.error(`Failed to save snapshot: ${err?.message ?? String(err)}`);
      setView("home");
    } finally {
      setIsWorking(false);
    }
  };

  // ── Quick loadout ─────────────────────────────────────────────────────────
  // Turn everything off, then put it all back exactly as it was. Only active pak
  // selections are recorded, so this stays a few kilobytes and can be captured
  // on every Disable All. Mod artwork is untouched: images live in the database
  // keyed by mod, while activation only moves .pak files in and out of ~mods.
  const handleDisableAllRemembering = async () => {
    const toastId = "loadout-disable-all";
    setIsWorking(true);
    toast.loading("Remembering current loadout…", { id: toastId });
    try {
      const { loadout, disabled } = await disableAllRemembering();
      if (disabled === 0) {
        toast.info("No active mods to disable", { id: toastId });
        return;
      }

      setSavedLoadout(loadout);
      onBackupRestored?.();
      toast.success(`Disabled ${disabled} mod(s) — loadout remembered`, {
        id: toastId,
        description: "Restore Loadout brings them back.",
      });
    } catch (err: any) {
      toast.error(`Failed to disable mods: ${err?.message ?? String(err)}`, { id: toastId });
    } finally {
      setIsWorking(false);
    }
  };

  const handleSavePreset = async () => {
    const name = presetName.trim();
    if (!name) return;
    setIsWorking(true);
    try {
      const saved = await savePreset(name);
      if (!saved) {
        toast.warning("Nothing is active — a preset would be empty", {
          description: "Enable the mods you want in this preset, then save it.",
        });
        return;
      }
      setPresets(listPresets());
      setPresetName("");
      toast.success(`Preset "${saved.name}" saved`, {
        description: `${saved.activeDownloads} mods · ${saved.activePaks} pak files`,
      });
    } catch (err: any) {
      toast.error(`Failed to save preset: ${err?.message ?? String(err)}`);
    } finally {
      setIsWorking(false);
    }
  };

  const handleApplyPreset = async (preset: Loadout) => {
    const toastId = "apply-preset";
    setIsWorking(true);
    toast.loading(`Applying "${preset.name}"…`, { id: toastId });
    try {
      const { updated, missing } = await restoreLoadout(preset);
      onBackupRestored?.();
      if (updated === 0) {
        toast.info(`Mods already match "${preset.name}"`, { id: toastId });
        return;
      }
      toast.success(`Applied "${preset.name}" — ${updated} mod(s) updated`, {
        id: toastId,
        description: missing > 0 ? `${missing} mod(s) no longer installed.` : undefined,
      });
    } catch (err: any) {
      toast.error(`Failed to apply preset: ${err?.message ?? String(err)}`, { id: toastId });
    } finally {
      setIsWorking(false);
    }
  };

  const handleDeletePreset = (preset: Loadout) => {
    deletePreset(preset.id);
    setPresets(listPresets());
    toast.success(`Preset "${preset.name}" deleted`);
  };

  const handleRestoreLoadout = async (target?: Loadout | null) => {
    const toastId = "loadout-restore";
    setIsWorking(true);
    toast.loading("Restoring loadout…", { id: toastId });
    try {
      const { updated, missing } = await restoreLoadout(target ?? savedLoadout);
      if (updated === 0) {
        toast.info("Mods already match this loadout", { id: toastId });
        return;
      }

      onBackupRestored?.();
      toast.success(`Loadout restored — ${updated} mod(s) updated`, {
        id: toastId,
        description: missing > 0 ? `${missing} mod(s) from the loadout are no longer installed.` : undefined,
      });
    } catch (err: any) {
      toast.error(`Failed to restore loadout: ${err?.message ?? String(err)}`, { id: toastId });
    } finally {
      setIsWorking(false);
    }
  };

  // ── Load backup for preview ───────────────────────────────────────────────
  const handleLoadBackup = async () => {
    setIsWorking(true);
    try {
      const path = await invokeOpenFileDialog(["zip", "json"]);
      if (!path) return;

      // A Full Snapshot is a backend-produced .zip holding the whole database.
      // It cannot be diffed against the mod list the way a .json projection can,
      // and it is restored by the backend rather than by replaying API calls, so
      // it takes a separate confirmation step.
      if (path.toLowerCase().endsWith(".zip")) {
        setArchivePath(path);
        setView("archive");
        return;
      }

      const content = await invokeReadTextFile(path);
      const backup = JSON.parse(content) as ModBackup;

      if (!backup.mods || !Array.isArray(backup.mods)) {
        toast.error("Invalid backup file — no mod list found");
        return;
      }

      const { toEnable, toDisable, missing } = computeRestoreDiff(
        backup,
        mods
      );
      setRestorePreview({ backup, filePath: path, toEnable, toDisable, missing });
      setView("restoring");
    } catch (err: any) {
      toast.error(`Failed to load backup: ${err?.message ?? String(err)}`);
    } finally {
      setIsWorking(false);
    }
  };

  /**
   * Restore straight from a listed backup.
   *
   * A v2 archive goes through the same confirmation as a browsed .zip — it
   * replaces the whole database, so the entry point must not change how much
   * warning the user gets. A v1 entry still needs its file read and diffed.
   */
  const handleSelectBackup = async (entry: UnifiedBackup) => {
    if (entry.generation === 2) {
      setArchivePath(entry.filePath);
      setView("archive");
      return;
    }

    setIsWorking(true);
    try {
      const content = await invokeReadTextFile(entry.filePath);
      const backup = JSON.parse(content) as ModBackup;
      if (!backup.mods || !Array.isArray(backup.mods)) {
        toast.error("Invalid backup file — no mod list found");
        return;
      }
      const { toEnable, toDisable, missing } = computeRestoreDiff(backup, mods);
      setRestorePreview({ backup, filePath: entry.filePath, toEnable, toDisable, missing });
      setView("restoring");
    } catch (err: any) {
      toast.error(`Could not open that backup: ${err?.message ?? String(err)}`);
    } finally {
      setIsWorking(false);
    }
  };

  /**
   * Restore whichever kind of point was clicked.
   *
   * The two paths are genuinely different — an archive replaces the whole
   * database and goes through a confirmation screen, a loadout only toggles pak
   * files — but that is a detail of what happens after the click, not a reason
   * to make the user find them in two different panels.
   */
  const handleRestorePoint = async (point: RestorePoint) => {
    if (point.kind === "loadout") {
      await handleRestoreLoadout(point.loadout ?? null);
      return;
    }
    if (point.backup) await handleSelectBackup(point.backup);
  };

  const handleDeleteRestorePoint = async (point: RestorePoint) => {
    if (point.kind === "loadout") {
      removeLoadout(point.id);
      setSavedLoadout(getLoadout(AUTO_LOADOUT_ID));
      toast.success("Remembered loadout cleared");
      return;
    }
    if (point.backup) await handleDeleteBackup(point.backup);
  };

  const handleDeleteBackup = async (entry: UnifiedBackup) => {
    setIsWorking(true);
    try {
      await deleteBackup(entry.filePath);
      toast.success(`Deleted "${entry.name}"`, {
        description: entry.sizeBytes > 0 ? `${formatBytes(entry.sizeBytes)} freed` : undefined,
      });
      await refreshBackupList();
      onBackupCreated?.();
    } catch (err: any) {
      toast.error(`Could not delete that backup: ${err?.message ?? String(err)}`);
    } finally {
      setIsWorking(false);
    }
  };

  // ── Apply archive (v2) restore ────────────────────────────────────────────
  const handleApplyArchiveRestore = async () => {
    if (!archivePath) return;
    const toastId = "archive-restore";
    setIsWorking(true);
    toast.loading("Restoring database from archive…", { id: toastId });
    try {
      const result = await restoreBackup(archivePath);
      await scanActive();
      await refreshConflicts();
      setView("restored");
      onBackupRestored?.();

      // Say what actually came back. "Database restored" was technically true
      // and useless: the mods stayed off, so it read as a lie.
      const re = result.reactivated;
      const parts: string[] = [];
      if (re && re.activated > 0) {
        parts.push(`${re.activated} mod${re.activated === 1 ? "" : "s"} switched back on`);
      }
      if (re && re.deactivated > 0) {
        parts.push(`${re.deactivated} turned off`);
      }
      if (re && re.failed > 0) {
        parts.push(`${re.failed} could not be restored — no longer on disk`);
      }
      if (result.safety_snapshot) {
        parts.push("A snapshot of your previous library was saved first.");
      }

      toast.success(
        re && re.activated > 0
          ? `Restored — ${re.activated} mod${re.activated === 1 ? "" : "s"} active again`
          : "Library restored from snapshot",
        {
          id: toastId,
          description: parts.length > 0 ? parts.join(" · ") : undefined,
          duration: 8000,
        },
      );
    } catch (err: any) {
      toast.error(`Restore failed: ${err?.message ?? String(err)}`, { id: toastId });
      setView("home");
    } finally {
      setIsWorking(false);
    }
  };

  // ── Apply restore ─────────────────────────────────────────────────────────
  const handleApplyRestore = async () => {
    if (!restorePreview) return;
    const { backup, toEnable, toDisable, missing } = restorePreview;

    setIsWorking(true);
    setView("restoring");

    try {
      let changed = 0;

      // Step 1 – Disable mods that were inactive in the backup (delta only — no nuclear sweep)
      for (const mod of toDisable) {
        const downloadIds = mod.sourceDownloadIds || [];
        for (const dlId of downloadIds) {
          await setActivePaks(Number(dlId), []);
        }
        changed++;
      }

      // Step 2 – Enable each mod in toEnable with its saved active variant paks
      for (const mod of toEnable) {
        // Find matching backup entry to get exact activePaks
        const backupEntry = backup.mods.find(e => {
          if (e.backendModId != null && mod.backendModId != null) {
            return e.backendModId === mod.backendModId;
          }
          if (e.sourceDownloadIds.length > 0 && Array.isArray(mod.sourceDownloadIds)) {
            return e.sourceDownloadIds.some(id => mod.sourceDownloadIds.includes(id));
          }
          return String(e.modId) === String(mod.id);
        });

        const backupDlIds = new Set<number>((backupEntry?.sourceDownloadIds || []).map(Number));
        const backupActivePaks = backupEntry?.activePaks || [];
        const backupActiveBases = new Set(backupActivePaks.map(p => {
          const parts = p.split(/[\/\\]/);
          return parts[parts.length - 1].toLowerCase();
        }));

        const currentDownloadIds = mod.sourceDownloadIds || [];
        for (const dlId of currentDownloadIds) {
          const numId = Number(dlId);
          if (!backupDlIds.has(numId)) {
            await setActivePaks(numId, []);
            continue;
          }

          if (backupActiveBases.size > 0) {
            const dl = await getLocalDownload(numId);
            const paks = (dl.contents || []).filter((f: string) => f.toLowerCase().endsWith(".pak"));
            const targetPaks = paks.filter((p: string) => {
              const parts = p.split(/[\/\\]/);
              return backupActiveBases.has(parts[parts.length - 1].toLowerCase());
            });
            await setActivePaks(numId, targetPaks);
          } else {
            const dl = await getLocalDownload(numId);
            const paks = (dl.contents || []).filter((f: string) => f.toLowerCase().endsWith(".pak"));
            await setActivePaks(numId, paks);
          }
        }
        changed++;
      }

      // Step 3 – Restore custom user data (tags, description, images)
      for (const mod of mods) {
        const backupEntry = backup.mods.find(e => {
          if (e.backendModId != null && mod.backendModId != null) return e.backendModId === mod.backendModId;
          if (e.sourceDownloadIds.length > 0 && Array.isArray(mod.sourceDownloadIds)) return e.sourceDownloadIds.some((id: number | string) => mod.sourceDownloadIds.includes(id));
          return String(e.modId) === String(mod.id);
        });
        
        if (!backupEntry) continue; // Only process mods that were in the backup

        const effectiveModId =
          mod.backendModId != null
            ? mod.backendModId
            : Array.isArray(mod.sourceDownloadIds) && mod.sourceDownloadIds.length > 0
              ? -mod.sourceDownloadIds[0]
              : null;
        if (effectiveModId == null) continue;

        // Restore custom tags
        const savedTags = backupEntry?.customTags || [];
        if (savedTags.length > 0) {
          for (const tagName of savedTags) {
            try { await addModCustomTag(effectiveModId, tagName); } catch { /* already exists or missing mod */ }
          }
        }

        // Restore custom description
        if (backupEntry?.description) {
          try {
            await updateModDetails(effectiveModId, { description: backupEntry.description });
          } catch { /* best effort */ }
        }

        // Restore custom images.
        //
        // The upload endpoint is a plain INSERT with no uniqueness constraint, so
        // restoring the same backup twice used to append every image again — and
        // this library stores gigabytes of artwork, so repeat restores grew the
        // database without bound.
        //
        // Dedup is by filename rather than by payload: uploads are re-encoded
        // server-side before they are stored, so the bytes held in the database
        // never equal the bytes in the backup file and a content comparison
        // would report "new" every single time.
        if (backupEntry?.customImages && backupEntry.customImages.length > 0) {
          try {
            const existing = await fetchModImages(effectiveModId);
            const haveNames = new Set(
              existing
                .filter((img) => img.source === "custom" && img.filename)
                .map((img) => String(img.filename).toLowerCase()),
            );
            const missing = backupEntry.customImages.filter(
              (img) => !img.filename || !haveNames.has(img.filename.toLowerCase()),
            );
            if (missing.length > 0) {
              await uploadModImagesBase64(effectiveModId, missing);
            }
          } catch { /* best effort */ }
        }
      }

      // Step 4 – Single filesystem sync
      await scanActive();
      await refreshConflicts();

      setView("restored");

      // Notify parent to refresh mod list from backend
      onBackupRestored?.();

      if (missing.length > 0) {
        toast.warning(
          `${missing.length} mod${missing.length > 1 ? "s" : ""} from this backup not installed`,
          {
            description: missing.slice(0, 5).join(", ") +
              (missing.length > 5 ? ` and ${missing.length - 5} more…` : ""),
            duration: 8000,
          }
        );
      }

      const totalChanges = toEnable.length + toDisable.length;
      if (totalChanges > 0) {
        toast.success(
          `Backup restored — ${totalChanges} mod${totalChanges > 1 ? "s" : ""} updated`
        );
      } else {
        toast.info("Mods already match this backup — no changes needed");
      }
    } catch (err: any) {
      console.error("Restore failed:", err);
      toast.error(`Restore failed: ${err?.message ?? String(err)}`);
      setView("home");
    } finally {
      setIsWorking(false);
    }
  };

  // ── Accent color ──────────────────────────────────────────────────────────
  const accentGradient =
    view === "created" || view === "restored"
      ? "linear-gradient(90deg, #22c55e, #10b981)"
      : view === "restoring" || view === "archive"
        ? "linear-gradient(90deg, #f59e0b, #f97316)"
        : "linear-gradient(90deg, #8b5cf6, #6366f1)";

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      {/* The card grew past the viewport once presets and the backup list were
          added, and `overflow: hidden` simply clipped it — the Presets section
          was unreachable on a short window. Cap the height and let the body
          scroll instead. Width falls back to a percentage on narrow windows so
          the dialog does not become a sliver. */}
      <DialogContent
        className="w-[50vw] max-w-[50vw] max-md:w-[92vw] max-md:max-w-[92vw]"
        style={{
          border: "1px solid hsl(var(--border))",
          borderRadius: "16px",
          maxHeight: "88vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Gradient accent bar */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: "4px",
            background: accentGradient,
            transition: "background 0.4s ease",
          }}
        />

        <DialogHeader className="pt-2">
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            {/* Icon */}
            <div
              style={{
                width: "44px",
                height: "44px",
                borderRadius: "12px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background:
                  view === "created" || view === "restored"
                    ? "linear-gradient(135deg, rgba(34,197,94,0.15), rgba(16,185,129,0.15))"
                    : view === "restoring"
                      ? "linear-gradient(135deg, rgba(245,158,11,0.15), rgba(249,115,22,0.15))"
                      : "linear-gradient(135deg, rgba(139,92,246,0.15), rgba(99,102,241,0.15))",
                flexShrink: 0,
                transition: "background 0.4s ease",
              }}
            >
              {view === "creating" ? (
                <Loader2 className="h-6 w-6 text-violet-400 animate-spin" />
              ) : view === "created" ? (
                <ShieldCheck className="h-6 w-6 text-emerald-400" />
              ) : view === "restored" ? (
                <CheckCircle2 className="h-6 w-6 text-emerald-400" />
              ) : view === "archive" ? (
                <AlertTriangle className="h-6 w-6 text-amber-400" />
              ) : view === "restoring" ? (
                <RotateCcw className="h-6 w-6 text-amber-400" />
              ) : (
                <Archive className="h-6 w-6 text-violet-400" />
              )}
            </div>

            {/* Title */}
            <div>
              <DialogTitle className="text-lg font-semibold">
                {view === "home"
                  ? "Mod Backup"
                  : view === "creating"
                    ? "Saving Backup…"
                    : view === "created"
                      ? "Backup Saved!"
                      : view === "archive"
                        ? "Restore Full Snapshot"
                        : view === "restoring"
                          ? "Restore Preview"
                          : "Restore Complete"}
              </DialogTitle>
              <p className="text-sm text-muted-foreground" style={{ marginTop: "2px" }}>
                {view === "home"
                  ? `${activeMods.length} active mods · ${installedMods.length} installed`
                  : view === "creating"
                    ? creatingStep === "gathering"
                      ? `Gathering metadata for ${installedMods.length} mod${installedMods.length !== 1 ? "s" : ""}…`
                      : "Choosing save location…"
                    : view === "created"
                      ? `${lastSavedMeta?.totalMods ?? 0} mods saved (${lastSavedMeta?.activeMods ?? 0} active)`
                      : view === "archive"
                        ? "Whole-database archive — review before applying"
                        : view === "restoring"
                          ? restorePreview?.backup.name ?? ""
                          : "Mod states have been updated"}
              </p>
            </div>
          </div>
        </DialogHeader>

        {/* Everything below the header scrolls as one body. */}
        <div
          className="custom-scrollbar"
          style={{ overflowY: "auto", overflowX: "hidden", flex: 1, minHeight: 0, paddingRight: "2px" }}
        >

        {/* ── HOME VIEW ── */}
        {view === "home" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px", paddingTop: "4px" }}>
            {/* Stats strip */}
            <div
              style={{
                display: "flex",
                gap: "12px",
                padding: "14px 16px",
                borderRadius: "12px",
                background: "hsl(var(--accent) / 0.3)",
                border: "1px solid hsl(var(--border) / 0.5)",
              }}
            >
              <div style={{ flex: 1, textAlign: "center" }}>
                <p className="text-2xl font-bold text-foreground">{activeMods.length}</p>
                <p className="text-xs text-muted-foreground mt-0.5">Active Mods</p>
              </div>
              <div style={{ width: "1px", background: "hsl(var(--border))" }} />
              <div style={{ flex: 1, textAlign: "center" }}>
                <p className="text-2xl font-bold text-foreground">{installedMods.length}</p>
                <p className="text-xs text-muted-foreground mt-0.5">Installed</p>
              </div>
            </div>

            {/* Create backup */}
            <div
              style={{
                padding: "16px",
                borderRadius: "12px",
                background: "linear-gradient(135deg, rgba(139,92,246,0.08), rgba(99,102,241,0.08))",
                border: "1px solid rgba(139,92,246,0.2)",
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: "12px" }}>
                <div
                  style={{
                    width: "36px",
                    height: "36px",
                    borderRadius: "8px",
                    background: "rgba(139,92,246,0.15)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <Archive className="h-4 w-4 text-violet-400" />
                </div>
                <div style={{ flex: 1 }}>
                  <p className="text-sm font-semibold text-foreground">Create Snapshot</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Full Snapshot saves everything. The .json export is portable
                    but carries little artwork.
                  </p>
                  <div style={{ display: "flex", gap: "8px", marginTop: "10px", flexWrap: "wrap" }}>
                    <Button
                      size="sm"
                      onClick={handleFullSnapshot}
                      disabled={isWorking || installedMods.length === 0}
                      style={{
                        background: "linear-gradient(135deg, #8b5cf6, #6366f1)",
                        border: "none",
                        fontWeight: 600,
                      }}
                      className="gap-2"
                    >
                      <ShieldCheck className="h-3.5 w-3.5" />
                      Full Snapshot
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleCreateBackup}
                      disabled={isWorking || installedMods.length === 0}
                      className="gap-2"
                    >
                      <Archive className="h-3.5 w-3.5" />
                      Export .json…
                    </Button>
                  </div>
                </div>
              </div>
            </div>

            {/* Restore */}
            <div
              style={{
                padding: "16px",
                borderRadius: "12px",
                background: "linear-gradient(135deg, rgba(245,158,11,0.08), rgba(249,115,22,0.08))",
                border: "1px solid rgba(245,158,11,0.2)",
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: "12px" }}>
                <div
                  style={{
                    width: "36px",
                    height: "36px",
                    borderRadius: "8px",
                    background: "rgba(245,158,11,0.15)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <RotateCcw className="h-4 w-4 text-amber-400" />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                    <p className="text-sm font-semibold text-foreground">Restore</p>
                    {latestRestorePoint && (
                      <Button
                        size="sm"
                        disabled={isWorking}
                        onClick={() => handleRestorePoint(latestRestorePoint)}
                        className="h-7 px-2.5 text-xs gap-1.5"
                        style={{
                          background: "linear-gradient(135deg, #f59e0b, #f97316)",
                          border: "none",
                          fontWeight: 600,
                        }}
                      >
                        <RotateCcw className="h-3 w-3" />
                        Restore latest
                      </Button>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Every save you have, newest first. Nothing is applied until
                    you confirm.
                  </p>

                  {restorePoints.length > 0 && (
                    <div
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: "6px",
                        marginTop: "10px",
                        maxHeight: "300px",
                        overflowY: "auto",
                        paddingRight: "4px",
                      }}
                    >
                      {restorePoints.map((point) => (
                        <div
                          key={point.id}
                          style={{
                            display: "flex",
                            alignItems: "flex-start",
                            gap: "8px",
                            padding: "8px 10px",
                            borderRadius: "8px",
                            background: "hsl(var(--accent) / 0.35)",
                            border: "1px solid hsl(var(--border) / 0.5)",
                          }}
                        >
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                              <span className="text-xs font-medium text-foreground truncate">
                                {point.name}
                              </span>
                              {/* The badge is where the backup/loadout
                                  distinction now lives: same list, same button,
                                  different reach. */}
                              <Badge
                                variant="outline"
                                className="text-xs shrink-0"
                                style={
                                  point.kind === "loadout"
                                    ? { borderColor: "rgba(56,189,248,0.5)", color: "#38bdf8" }
                                    : point.kind === "full"
                                      ? { borderColor: "rgba(139,92,246,0.5)", color: "#a78bfa" }
                                      : undefined
                                }
                              >
                                {point.kind === "loadout"
                                  ? "mods on/off"
                                  : point.kind === "full"
                                    ? "whole library"
                                    : ".json"}
                              </Badge>
                              {point.backup && point.backup.kind !== "manual" && (
                                <Badge variant="secondary" className="text-xs shrink-0">
                                  automatic
                                </Badge>
                              )}
                            </div>

                            <p className="text-xs text-muted-foreground mt-0.5">
                              {RESTORE_POINT_SCOPE[point.kind]}
                            </p>

                            <p className="text-xs text-muted-foreground/70 mt-0.5">
                              {formatWhen(point.createdAt)}
                              {point.summary ? ` · ${point.summary}` : ""}
                              {point.backup && point.backup.sizeBytes > 0
                                ? ` · ${formatBytes(point.backup.sizeBytes)}`
                                : ""}
                            </p>
                          </div>

                          <div style={{ display: "flex", gap: "4px", flexShrink: 0 }}>
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={isWorking}
                              onClick={() => handleRestorePoint(point)}
                              className="h-7 px-2 text-xs gap-1"
                              style={{ borderColor: "rgba(245,158,11,0.4)", color: "#f59e0b" }}
                            >
                              <RotateCcw className="h-3 w-3" />
                              Restore
                            </Button>
                            {/* A .json export lives wherever the user saved it,
                                so the app has no business deleting it. */}
                            {point.kind !== "export" && (
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={isWorking}
                                onClick={() => handleDeleteRestorePoint(point)}
                                className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                                title={`Delete "${point.name}"`}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Where these live, so they can be found outside the app. */}
                  {backupsFolder && (
                    <p className="text-xs text-muted-foreground/60 mt-2 break-all font-mono">
                      {backupsFolder}
                    </p>
                  )}

                  {restorePoints.length === 0 && !loadingBackups && (
                    <p className="text-xs text-muted-foreground/60 mt-2">
                      Nothing saved yet. Create a Full Snapshot above.
                    </p>
                  )}

                  <div style={{ display: "flex", gap: "8px", marginTop: "10px", flexWrap: "wrap" }}>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleLoadBackup}
                      disabled={isWorking}
                      className="gap-2"
                      style={{ borderColor: "rgba(245,158,11,0.4)", color: "#f59e0b" }}
                    >
                      <FolderOpen className="h-3.5 w-3.5" />
                      Browse for a file…
                    </Button>
                    {/* Turning everything off records a restore point first, so
                        it belongs next to the list it adds to. */}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleDisableAllRemembering}
                      disabled={isWorking || activeMods.length === 0}
                      className="gap-2"
                      style={{ borderColor: "rgba(56,189,248,0.4)", color: "#38bdf8" }}
                    >
                      <Power className="h-3.5 w-3.5" />
                      Turn all mods off
                    </Button>
                  </div>
                </div>
              </div>
            </div>

            {/* Named presets — save several setups and switch between them */}
            <div
              style={{
                padding: "16px",
                borderRadius: "12px",
                background: "linear-gradient(135deg, rgba(168,85,247,0.08), rgba(217,70,239,0.08))",
                border: "1px solid rgba(168,85,247,0.2)",
              }}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: "12px" }}>
                <div
                  style={{
                    width: "36px",
                    height: "36px",
                    borderRadius: "8px",
                    background: "rgba(168,85,247,0.15)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <Bookmark className="h-4 w-4 text-fuchsia-400" />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p className="text-sm font-semibold text-foreground">Presets</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Save the current setup under a name and switch back any time.
                  </p>

                  <div style={{ display: "flex", gap: "8px", marginTop: "10px" }}>
                    <input
                      value={presetName}
                      onChange={(e) => setPresetName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleSavePreset();
                      }}
                      placeholder="Preset name — e.g. PvP"
                      maxLength={60}
                      className="flex-1 min-w-0 text-xs bg-background border border-border rounded px-2 py-1.5"
                    />
                    <Button
                      size="sm"
                      onClick={handleSavePreset}
                      disabled={isWorking || !presetName.trim() || activeMods.length === 0}
                      className="gap-1.5 shrink-0"
                      style={{
                        background: "linear-gradient(135deg, #a855f7, #d946ef)",
                        border: "none",
                        fontWeight: 600,
                      }}
                    >
                      <Bookmark className="h-3.5 w-3.5" />
                      Save
                    </Button>
                  </div>

                  {presets.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "10px" }}>
                      {presets.map((preset) => (
                        <div
                          key={preset.id}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "8px",
                            padding: "7px 10px",
                            borderRadius: "8px",
                            background:
                              preset.id === activePresetId
                                ? "rgba(168,85,247,0.14)"
                                : "hsl(var(--accent) / 0.35)",
                            border:
                              preset.id === activePresetId
                                ? "1px solid rgba(168,85,247,0.55)"
                                : "1px solid hsl(var(--border) / 0.5)",
                          }}
                        >
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                              <p className="text-xs font-medium text-foreground truncate">
                                {preset.name}
                              </p>
                              {preset.id === activePresetId && (
                                <Badge
                                  className="text-xs shrink-0"
                                  style={{ background: "#a855f7", color: "white" }}
                                >
                                  Loaded
                                </Badge>
                              )}
                            </div>
                            <p className="text-xs text-muted-foreground/70">
                              {preset.activeDownloads} mods · {preset.activePaks} paks
                            </p>
                          </div>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={isWorking || preset.id === activePresetId}
                            onClick={() => handleApplyPreset(preset)}
                            className="h-7 px-2 text-xs gap-1 shrink-0"
                          >
                            <Power className="h-3 w-3" />
                            {preset.id === activePresetId ? "Active" : "Apply"}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={isWorking}
                            onClick={() => handleDeletePreset(preset)}
                            className="h-7 w-7 p-0 shrink-0 text-muted-foreground hover:text-destructive"
                            title={`Delete preset "${preset.name}"`}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground/60 mt-2">
                      No presets yet. Enable the mods you want, name the setup, and save.
                    </p>
                  )}
                </div>
              </div>
            </div>

            <p className="text-xs text-center text-muted-foreground/60 pb-1">
              Backups also appear in the <strong>Collections</strong> tab for quick switching.
            </p>
          </div>
        )}

        {/* ── CREATING VIEW (spinner) ── */}
        {view === "creating" && (
          <div className="flex flex-col items-center justify-center py-10 gap-5">
            <Loader2 className="h-10 w-10 text-violet-400 animate-spin" />
            <div className="flex flex-col items-center gap-1.5">
              <p className="text-sm font-medium text-foreground">
                {creatingStep === "gathering"
                  ? "Collecting mod metadata…"
                  : "Opening save dialog…"}
              </p>
              <p className="text-xs text-muted-foreground">
                {creatingStep === "gathering"
                  ? `Reading tags, descriptions & images for ${installedMods.length} mod${installedMods.length !== 1 ? "s" : ""}`
                  : "Choose where to save your backup file"}
              </p>
            </div>
          </div>
        )}

        {/* ── CREATED VIEW ── */}
        {view === "created" && lastSavedMeta && (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px", paddingTop: "4px" }}>
            <div
              style={{
                padding: "16px",
                borderRadius: "12px",
                background: "rgba(34,197,94,0.08)",
                border: "1px solid rgba(34,197,94,0.2)",
                display: "flex",
                flexDirection: "column",
                gap: "10px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                <span className="text-sm font-semibold text-emerald-300">{lastSavedMeta.name}</span>
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <Badge variant="secondary" className="text-xs gap-1">
                  <Power className="h-3 w-3" /> {lastSavedMeta.activeMods} active
                </Badge>
                <Badge variant="secondary" className="text-xs gap-1">
                  <Download className="h-3 w-3" /> {lastSavedMeta.totalMods} total
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground break-all font-mono">
                {lastSavedMeta.filePath}
              </p>
            </div>
            <p className="text-xs text-muted-foreground text-center pb-1">
              This backup is now listed in your <strong>Collections</strong> tab.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
              <Button variant="outline" size="sm" onClick={() => setView("home")} className="gap-2">
                <Archive className="h-3.5 w-3.5" /> Another Backup
              </Button>
              <Button
                size="sm"
                onClick={onClose}
                style={{ background: "linear-gradient(135deg, #22c55e, #10b981)", border: "none", fontWeight: 600 }}
              >
                Done
              </Button>
            </div>
          </div>
        )}

        {/* ── RESTORE PREVIEW VIEW ── */}
        {view === "restoring" && restorePreview && (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px", paddingTop: "4px" }}>
            {/* Changes summary */}
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {restorePreview.toEnable.length > 0 && (
                <div
                  style={{
                    flex: 1,
                    padding: "12px 14px",
                    borderRadius: "10px",
                    background: "rgba(34,197,94,0.08)",
                    border: "1px solid rgba(34,197,94,0.2)",
                    minWidth: "120px",
                  }}
                >
                  <p className="text-xl font-bold text-emerald-400">{restorePreview.toEnable.length}</p>
                  <p className="text-xs text-muted-foreground">will enable</p>
                </div>
              )}
              {restorePreview.toDisable.length > 0 && (
                <div
                  style={{
                    flex: 1,
                    padding: "12px 14px",
                    borderRadius: "10px",
                    background: "rgba(239,68,68,0.08)",
                    border: "1px solid rgba(239,68,68,0.2)",
                    minWidth: "120px",
                  }}
                >
                  <p className="text-xl font-bold text-red-400">{restorePreview.toDisable.length}</p>
                  <p className="text-xs text-muted-foreground">will disable</p>
                </div>
              )}
              {restorePreview.missing.length > 0 && (
                <div
                  style={{
                    flex: 1,
                    padding: "12px 14px",
                    borderRadius: "10px",
                    background: "rgba(245,158,11,0.08)",
                    border: "1px solid rgba(245,158,11,0.2)",
                    minWidth: "120px",
                  }}
                >
                  <p className="text-xl font-bold text-amber-400">{restorePreview.missing.length}</p>
                  <p className="text-xs text-muted-foreground">not installed</p>
                </div>
              )}
              {restorePreview.toEnable.length === 0 && restorePreview.toDisable.length === 0 && (
                <div
                  style={{
                    flex: 1,
                    padding: "12px 14px",
                    borderRadius: "10px",
                    background: "hsl(var(--accent) / 0.3)",
                    border: "1px solid hsl(var(--border) / 0.5)",
                  }}
                >
                  <p className="text-sm font-semibold text-foreground">Already up to date</p>
                  <p className="text-xs text-muted-foreground">No mod state changes needed.</p>
                </div>
              )}
            </div>

            {/* Missing mods warning */}
            {restorePreview.missing.length > 0 && (
              <div
                style={{
                  padding: "12px 14px",
                  borderRadius: "10px",
                  background: "rgba(245,158,11,0.06)",
                  border: "1px solid rgba(245,158,11,0.2)",
                  display: "flex",
                  gap: "8px",
                  alignItems: "flex-start",
                }}
              >
                <AlertTriangle className="h-4 w-4 text-amber-400 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-xs font-semibold text-amber-300">Not installed:</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {restorePreview.missing.slice(0, 4).join(", ")}
                    {restorePreview.missing.length > 4 ? ` +${restorePreview.missing.length - 4} more` : ""}
                  </p>
                  <p className="text-xs text-muted-foreground/70 mt-1">
                    Download these mods from Nexus to fully restore this backup.
                  </p>
                </div>
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
              <Button variant="ghost" size="sm" onClick={() => setView("home")}>
                Back
              </Button>
              <Button
                size="sm"
                onClick={handleApplyRestore}
                style={{
                  background: "linear-gradient(135deg, #f59e0b, #f97316)",
                  border: "none",
                  fontWeight: 600,
                }}
                className="gap-2"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Apply Restore
              </Button>
            </div>
          </div>
        )}

        {/* ── ARCHIVE (v2 zip) CONFIRMATION VIEW ── */}
        {view === "archive" && archivePath && (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px", paddingTop: "4px" }}>
            <div
              style={{
                padding: "14px 16px",
                borderRadius: "12px",
                background: "rgba(245,158,11,0.08)",
                border: "1px solid rgba(245,158,11,0.25)",
                display: "flex",
                gap: "10px",
                alignItems: "flex-start",
              }}
            >
              <AlertTriangle className="h-5 w-5 text-amber-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-amber-300">
                  This replaces your entire mod database
                </p>
                {/* Kept explicit: this is destructive, and the undo is the one
                    thing worth spending words on. */}
                <p className="text-xs text-muted-foreground mt-1">
                  Every mod, tag and image is replaced by the archive. Your
                  current database is snapshotted first, so this can be undone.
                </p>
              </div>
            </div>

            <p className="text-xs text-muted-foreground break-all font-mono">{archivePath}</p>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
              <Button variant="ghost" size="sm" disabled={isWorking} onClick={() => setView("home")}>
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={isWorking}
                onClick={handleApplyArchiveRestore}
                style={{
                  background: "linear-gradient(135deg, #f59e0b, #f97316)",
                  border: "none",
                  fontWeight: 600,
                }}
                className="gap-2"
              >
                {isWorking ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RotateCcw className="h-3.5 w-3.5" />
                )}
                Restore Database
              </Button>
            </div>
          </div>
        )}

        {/* ── RESTORED VIEW ── */}
        {view === "restored" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px", paddingTop: "4px" }}>
            <div
              style={{
                padding: "16px",
                borderRadius: "12px",
                background: "rgba(34,197,94,0.08)",
                border: "1px solid rgba(34,197,94,0.2)",
                display: "flex",
                alignItems: "center",
                gap: "12px",
              }}
            >
              <CheckCircle2 className="h-6 w-6 text-emerald-400 flex-shrink-0" />
              <div>
                <p className="text-sm font-semibold text-emerald-300">Restore applied!</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Your mod active states have been updated to match the backup.
                </p>
              </div>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <Button
                size="sm"
                onClick={onClose}
                style={{
                  background: "linear-gradient(135deg, #22c55e, #10b981)",
                  border: "none",
                  fontWeight: 600,
                }}
              >
                Done
              </Button>
            </div>
          </div>
        )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
