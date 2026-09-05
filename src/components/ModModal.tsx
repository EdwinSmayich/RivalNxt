import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
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
import { Button } from "./ui/button";
import { AuthorPopover } from "./AuthorPopover";
import { Badge } from "./ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "./ui/avatar";
import { Separator } from "./ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import { Textarea } from "./ui/textarea";
import {
  Download,
  Star,
  Heart,
  Calendar,
  File,
  Trash2,
  ExternalLink,
  Plus,
  X,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  FolderOpen,
  Pencil,
  Check,
  X as XIcon,
  RefreshCw,
  AlertTriangle,
  Link,
  AlertCircle,
  Loader2,
  GripVertical,
  Search,
  ClipboardCopy,
  EyeOff,
  RotateCcw,
  Image as ImageIcon
} from "lucide-react";
import type { Mod } from "./ModCard";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type SyntheticEvent,
} from "react";
import DOMPurify from "dompurify";
import {
  getModChangelogs,
  getModDetails,
  getPakAssets,
  fetchModImages,
  fetchModImagesDetailed,
  listArchiveImages,
  importArchiveImages,
  setNexusImageHidden,
  getFileNotes,
  setFileNote,
  searchNexusImages,
  type ArchiveImage,
  type NexusImageResult,
  uploadModImages,
  uploadModImagesByPath,
  uploadModImagesByUrl,
  reorderModImages,
  setModImagePreview,
  removeDownloadFile,
  deleteModImage,
  updateModDetails,
  getModCustomTags,
  getModHiddenTags,
  hideModTag,
  unhideModTag,
  addModCustomTag,
  removeModCustomTag,
  getAllCustomTags,
  type ApiChangelog,
  type ApiModDetails,
  type ApiPakAsset,
  type ModImage,
  type CustomTag,
} from "../lib/api";
import { Switch } from "./ui/switch";
import {
  setActivePaks,
  scanActive,
  getLocalDownload,
  getPakVersionStatus,
  refreshConflicts,
  restoreDownloadFile,
  deleteLocalDownloads,
  deleteDownloadFile,
  type ApiPakVersionStatus,
} from "../lib/api";
import { toast } from "sonner";
import React from "react";

type DownloadEntry = {
  id: number;
  path: string;
  contents: string[];
  /** Files removed from this mod. Kept out of `contents`, shown on request. */
  hidden_contents: string[];
  active_paks: string[];
  version: string | null;
  created_at?: string | null;
  name?: string | null;
  // NEW fields (already returned by /api/local_downloads/:id)
  local_version_key?: string | null;
  latest_version?: string | null;
  latest_version_key?: string | null;
  latest_file_id?: number | null;
  needs_update?: boolean;
  mod_id?: number | null;
  source_file_ids?: number[];
};

type PakGroup = { primary: string; files: string[] };

function groupPakEntries(contents: string[] | null | undefined): PakGroup[] {
  if (!Array.isArray(contents)) {
    return [];
  }
  const groups = new Map<string, PakGroup>();
  for (const fileName of contents) {
    if (typeof fileName !== "string" || !fileName) continue;
    const stem = fileName.replace(/\.(pak|utoc|ucas|sig)$/i, "");
    const key = stem || fileName;
    const current = groups.get(key) ?? { primary: fileName, files: [] };
    current.files.push(fileName);
    if (/\.pak$/i.test(fileName)) {
      current.primary = fileName;
    } else if (!/\.pak$/i.test(current.primary)) {
      current.primary = current.primary || fileName;
    }
    groups.set(key, current);
  }
  return Array.from(groups.values()).filter((entry) =>
    entry.files.some((file) => /\.pak$/i.test(file)),
  );
}

/** Tree node for hierarchical file display */
type FileTreeNode = {
  name: string;
  children: FileTreeNode[];
  group?: PakGroup; // present only on leaf nodes (files)
};

/** Build a folder tree from pak groups for hierarchical display */
function buildFileTree(groups: PakGroup[]): FileTreeNode {
  const root: FileTreeNode = { name: "", children: [] };

  for (const group of groups) {
    const parts = group.primary.replace(/\\/g, "/").split("/");
    let current = root;

    // All parts except the last are folder segments
    for (let i = 0; i < parts.length - 1; i++) {
      const folderName = parts[i];
      let child = current.children.find(
        (c) => c.name === folderName && !c.group,
      );
      if (!child) {
        child = { name: folderName, children: [] };
        current.children.push(child);
      }
      current = child;
    }

    // Last part is the file (leaf node)
    current.children.push({
      name: parts[parts.length - 1],
      children: [],
      group,
    });
  }

  return collapseFileTree(root);
}

/** Collapse single-child folder chains to reduce redundant nesting */
function collapseFileTree(node: FileTreeNode): FileTreeNode {
  if (node.group) return node; // leaf node
  node.children = node.children.map(collapseFileTree);
  // Merge single-child folder chains: A > B > file => "A / B" > file
  while (
    node.children.length === 1 &&
    !node.children[0].group &&
    node.name !== ""
  ) {
    const child = node.children[0];
    node.name = `${node.name} / ${child.name}`;
    node.children = child.children;
  }
  return node;
}

/** Recursive tree renderer for hierarchical pak file display */
/**
 * Props shared by every level of the file tree.
 *
 * Grouped into one type because the tree is mutually recursive and the removal
 * callbacks previously stopped at the flat-list branch: an archive whose paks
 * sat in a subfolder rendered through here instead, where no delete button had
 * been threaded through. Most real mods ship exactly that layout, so per-file
 * deletion looked missing to anyone who had one.
 */
interface FileTreeProps {
  entryId: number;
  activeList: string[];
  switchDisabled: boolean;
  handleToggle: (
    downloadId: number,
    files: string[],
    willCheck: boolean,
  ) => void;
  /** Name of the pak currently being hidden, or null. */
  removingFile: string | null;
  onRemoveFile: (downloadId: number, pakName: string) => void;
  /** Name of the pak currently being deleted from the archive, or null. */
  deletingFile: string | null;
  onDeleteFile: (downloadId: number, pakName: string) => void;
  /** Notes keyed by pak basename. */
  notes: Record<string, string>;
  onEditNote: (downloadId: number, pakName: string) => void;
}

/**
 * A one-liner the user runs in their own browser, on the gallery page they are
 * already looking at, to collect every image address at once.
 *
 * This exists because the app cannot read that page itself: Nexus exposes no
 * per-mod image list through either API, and the mod page answers automated
 * requests with a Cloudflare challenge. A real browser passes that check by
 * being a real browser — so the browser does the reading, and the user pastes
 * the result back. Same as right-clicking each picture in turn, minus the nine
 * right-clicks.
 *
 * Thumbnails are rewritten to their full-size path, and duplicates dropped,
 * because the grid shows each image twice — once as a thumbnail, once as the
 * link behind it.
 */
const GALLERY_URL_SNIPPET =
  "copy([...document.querySelectorAll('img, a, [data-src]')]" +
  ".flatMap(e => [e.src, e.href, e.dataset && e.dataset.src])" +
  ".filter(u => typeof u === 'string' && /staticdelivery\\.nexusmods\\.com\\/mods\\/\\d+\\/images\\//.test(u))" +
  ".map(u => u.split('?')[0].replace('/images/thumbnails/', '/images/'))" +
  ".filter((u, i, a) => a.indexOf(u) === i).join('\\n'))";

/**
 * When the "delete a file from the archive" confirmation may be skipped until.
 *
 * A timestamp rather than a boolean: the mute is meant to last one day, so a
 * habit formed today cannot quietly destroy something next month.
 */
const DELETE_PROMPT_MUTED_UNTIL = "rivalnxt.deleteFilePrompt.mutedUntil";

/** Notes are keyed by basename so a path change cannot orphan them. */
function noteKey(pakName: string): string {
  const parts = pakName.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1];
}

/** The note row under a file, shown only when there is something to show. */
function FileNote({ note }: { note?: string }) {
  if (!note) return null;
  return (
    <p className="text-xs text-muted-foreground mt-1 pl-7 break-words whitespace-pre-wrap">
      {note}
    </p>
  );
}

function FileTreeRenderer({
  nodes,
  depth,
  ...shared
}: FileTreeProps & {
  nodes: FileTreeNode[];
  depth: number;
}) {
  const {
    entryId,
    activeList,
    switchDisabled,
    handleToggle,
    removingFile,
    onRemoveFile,
    deletingFile,
    onDeleteFile,
    notes,
    onEditNote,
  } = shared;
  return (
    <>
      {nodes.map((node) => {
        if (node.group) {
          // Leaf node — render file with toggle
          const { files, primary } = node.group;
          const checked = files.some((file) => activeList.includes(file));
          const note = notes[noteKey(primary)];
          return (
            <div
              key={`${entryId}-${primary}`}
              className={`mod-file-item rounded-lg ${
                checked ? "bg-green-100 dark:bg-green-900/60" : "bg-popover"
              }`}
              style={{ marginLeft: depth * 16, padding: "6px" }}
            >
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <File className="w-4 h-4 text-muted-foreground shrink-0" />
                  <div className="font-medium truncate">{node.name}</div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => onEditNote(entryId, primary)}
                    className={`p-1 rounded transition-colors ${
                      note
                        ? "text-amber-500 hover:bg-amber-500/10"
                        : "text-muted-foreground/50 hover:text-foreground hover:bg-muted"
                    }`}
                    title={note ? `Note: ${note}` : "Add a note"}
                    aria-label={note ? "Edit note" : "Add a note"}
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <Switch
                    disabled={switchDisabled}
                    checked={checked}
                    onCheckedChange={(willCheck: boolean) =>
                      handleToggle(entryId, files, willCheck)
                    }
                  />
                  {/* Two different things, so two different icons. The eye
                      hides — reversible, the file stays in the archive. The bin
                      deletes it out of the archive for good. They used to be the
                      same bin, which made the safe action look like the
                      dangerous one. */}
                  <button
                    type="button"
                    disabled={removingFile === primary}
                    onClick={() => onRemoveFile(entryId, primary)}
                    className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-40"
                    title={`Hide ${node.name} — stays in the archive`}
                    aria-label={`Hide ${node.name}`}
                  >
                    {removingFile === primary ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <EyeOff className="w-4 h-4" />
                    )}
                  </button>
                  <button
                    type="button"
                    disabled={deletingFile === primary}
                    onClick={() => onDeleteFile(entryId, primary)}
                    className="p-1 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 disabled:opacity-40"
                    title={`Delete ${node.name} from the archive — permanent`}
                    aria-label={`Delete ${node.name} permanently`}
                  >
                    {deletingFile === primary ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Trash2 className="w-4 h-4" />
                    )}
                  </button>
                </div>
              </div>
              <FileNote note={note} />
            </div>
          );
        }

        // Folder node — render collapsible section
        return (
          <FileTreeFolderNode
            key={`${entryId}-folder-${node.name}`}
            node={node}
            depth={depth}
            {...shared}
          />
        );
      })}
    </>
  );
}

/** Collapsible folder node in the file tree */
function FileTreeFolderNode({
  node,
  depth,
  ...shared
}: FileTreeProps & {
  node: FileTreeNode;
  depth: number;
}) {
  const [expanded, setExpanded] = useState(true);
  const ChevronIcon = expanded ? ChevronDown : ChevronRight;

  return (
    <div style={{ marginLeft: depth * 16 }}>
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-muted/50 transition-colors w-full text-left group"
      >
        <ChevronIcon className="w-3.5 h-3.5 text-muted-foreground shrink-0 transition-transform" />
        <FolderOpen className="w-4 h-4 text-amber-500 shrink-0" />
        <span className="text-sm font-medium text-muted-foreground group-hover:text-foreground transition-colors truncate">
          {node.name}
        </span>
      </button>
      {expanded && (
        <div className="space-y-2 mt-1">
          <FileTreeRenderer
            nodes={node.children}
            depth={depth + 1}
            {...shared}
          />
        </div>
      )}
    </div>
  );
}

function toActiveMap(entries: DownloadEntry[]): Record<number, string[]> {
  const map: Record<number, string[]> = {};
  for (const entry of entries) {
    map[entry.id] = Array.isArray(entry.active_paks)
      ? [...entry.active_paks]
      : [];
  }
  return map;
}

const toBasename = (value: string): string => {
  if (typeof value !== "string") return "";
  const parts = value.split(/[/\\]/);
  const last = parts[parts.length - 1];
  return last || value;
};

const normalizeVersion = (version?: string | null): string => {
  if (!version) return "Unknown";
  const trimmed = version.trim();
  if (!trimmed) return "Unknown";
  const dotParts = trimmed.split(".").filter(Boolean);
  if (dotParts.length > 0) {
    const limited = dotParts.slice(0, 3).map((part, index) => {
      if (index === 0) return part;
      if (part.length > 3) {
        return part.slice(0, 3);
      }
      return part;
    });
    return limited.join(".");
  }
  const numericParts = trimmed.match(/\d+/g);
  if (numericParts && numericParts.length > 0) {
    return numericParts
      .slice(0, 3)
      .map((part, index) => {
        if (index === 0) return part;
        return part.slice(0, 3);
      })
      .join(".");
  }
  return trimmed;
};

const getDownloadDisplayName = (entry: DownloadEntry): string => {
  if (!entry) {
    return "Download";
  }
  if (entry.name && entry.name.trim().length > 0) {
    return entry.name.trim();
  }
  if (entry.path && entry.path.trim().length > 0) {
    const base = toBasename(entry.path.trim());
    if (base.length > 0) {
      return base;
    }
  }
  return `Download #${entry.id}`;
};

interface ModModalProps {
  mod: Mod | null;
  isOpen: boolean;
  onClose: () => void;
  onInstall: (modId: string) => void;
  onFavorite: (modId: string) => void;
  onConflictStateChanged?: () => void;
  onRefresh?: (opts?: { skipScan?: boolean }) => void;
  // NEW: open on a specific tab (default = "overview")
  initialTab?: "overview" | "files" | "changelog" | "images" | "assets";
  // NEW: called when user clicks Update on a specific variant
  onUpdate?: (modId: string, downloadId?: number) => void | Promise<void>;
  onAssignModId?: (modId: string) => void;
}

export function ModModal({
  mod,
  isOpen,
  onClose,
  onInstall,
  onFavorite,
  onConflictStateChanged,
  onRefresh,
  initialTab,
  onUpdate,
  onAssignModId,
}: ModModalProps) {
  const [details, setDetails] = useState<ApiModDetails | null>(null);
  // Files list from server is not needed for toggle UI; using local download contents instead
  // const [files, setFiles] = useState<ApiModFile[] | null>(null);
  const [changelogs, setChangelogs] = useState<ApiChangelog[] | null>(null);
  const [pakAssets, setPakAssets] = useState<ApiPakAsset[]>([]);

  // Determine effective mod ID for images (Nexus ID or negative local download ID)
  const effectiveModId = useMemo(() => {
    if (mod?.backendModId) return mod.backendModId;
    if (mod?.sourceDownloadIds && mod.sourceDownloadIds.length > 0) {
      // Use the first source download ID as a stable negative ID for local mods
      return -mod.sourceDownloadIds[0];
    }
    return null;
  }, [mod]);

  // Fetch from backend if we have a linked mods.mod_id which is strictly for Nexus details
  const serverModId = useMemo(() => mod?.backendModId ?? null, [mod]);
  const [isApplying, setIsApplying] = useState(false);
  const downloadIds = useMemo(
    () =>
      Array.isArray(mod?.sourceDownloadIds)
        ? mod.sourceDownloadIds
            .map((id) => Number(id))
            .filter((id) => Number.isFinite(id))
        : [],
    [mod?.sourceDownloadIds],
  );
  const [downloadEntries, setDownloadEntries] = useState<DownloadEntry[]>([]);
  const [activeByDownload, setActiveByDownload] = useState<
    Record<number, string[]>
  >({});
  const [pakStatusByDownload, setPakStatusByDownload] = useState<
    Record<number, Record<string, ApiPakVersionStatus>>
  >({});
  const [deletingDownloadId, setDeletingDownloadId] = useState<number | null>(
    null,
  );
  const [deleteDialogEntry, setDeleteDialogEntry] =
    useState<DownloadEntry | null>(null);

  // Images state
  const [modImages, setModImages] = useState<ModImage[]>([]);
  /** The mod has a Nexus picture, but the user removed it from the gallery. */
  const [nexusImageIsHidden, setNexusImageIsHidden] = useState(false);
  const [archivePickerOpen, setArchivePickerOpen] = useState(false);
  const [archiveScanning, setArchiveScanning] = useState(false);
  const [archiveImporting, setArchiveImporting] = useState(false);
  const [archiveImages, setArchiveImages] = useState<ArchiveImage[]>([]);
  const [archiveSelection, setArchiveSelection] = useState<Set<string>>(new Set());
  const [nexusSearchOpen, setNexusSearchOpen] = useState(false);
  const [nexusSearching, setNexusSearching] = useState(false);
  const [nexusSearchInput, setNexusSearchInput] = useState("");
  const [nexusResults, setNexusResults] = useState<NexusImageResult[]>([]);
  const [nexusSelection, setNexusSelection] = useState<Set<string>>(new Set());
  /** downloadId -> { pak basename -> note }. */
  const [fileNotes, setFileNotes] = useState<Record<number, Record<string, string>>>({});
  const [noteTarget, setNoteTarget] = useState<
    { downloadId: number; pakName: string } | null
  >(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [savingNote, setSavingNote] = useState(false);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [isUploadingImages, setIsUploadingImages] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = React.useRef(0);

  // Description editing state
  const [isEditingDescription, setIsEditingDescription] = useState(false);
  const [editDescriptionValue, setEditDescriptionValue] = useState("");
  const [isSavingDescription, setIsSavingDescription] = useState(false);
  const [isBBCodeMode, setIsBBCodeMode] = useState(false);

  // Custom tag state
  const [customTags, setCustomTags] = useState<CustomTag[]>([]);
  const [removedTagNames, setRemovedTagNames] = useState<Set<string>>(new Set());
  /** Auto-detected tags suppressed for this mod, so they can be restored. */
  const [hiddenTags, setHiddenTags] = useState<string[]>([]);
  const [imageUrlInput, setImageUrlInput] = useState("");
  const [isAddingImageUrls, setIsAddingImageUrls] = useState(false);
  const [isReordering, setIsReordering] = useState(false);
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dragOverId, setDragOverId] = useState<number | null>(null);
  const [removingFile, setRemovingFile] = useState<string | null>(null);
  const [restoringFile, setRestoringFile] = useState<string | null>(null);
  const [deletingFile, setDeletingFile] = useState<string | null>(null);
  const [deleteFileTarget, setDeleteFileTarget] = useState<
    { downloadId: number; pakName: string } | null
  >(null);
  const [suppressDeletePrompt, setSuppressDeletePrompt] = useState(false);
  /** The step-by-step for the gallery helper, expanded on first use. */
  const [galleryStepsOpen, setGalleryStepsOpen] = useState(false);
  /** Download ids whose Hidden list is expanded. */
  const [hiddenOpenFor, setHiddenOpenFor] = useState<Set<number>>(new Set());
  const [allTagSuggestions, setAllTagSuggestions] = useState<string[]>([]);
  const [isTagDropdownOpen, setIsTagDropdownOpen] = useState(false);
  const [tagSearchValue, setTagSearchValue] = useState("");
  const [isAddingTag, setIsAddingTag] = useState(false);
  const tagDropdownRef = useRef<HTMLDivElement>(null);

  const [currentTab, setCurrentTab] = useState<string>(initialTab ?? "overview");

  useEffect(() => {
    if (isOpen) {
      setCurrentTab(initialTab ?? "overview");
    }
  }, [isOpen, initialTab]);

  // Custom preset that includes standard HTML5 tags + size, font, alignment

  const overviewTags = useMemo(() => {
    const tags: string[] = [];
    const seen = new Set<string>();
    
    // Add custom tag names to seen set so they aren't duplicate-added to overviewTags
    if (Array.isArray(customTags)) {
      customTags.forEach(ct => {
        if (ct?.tag) {
          seen.add(ct.tag.toLowerCase().trim());
        }
      });
    }

    // Prevent recently removed tag names from temporarily appearing in overview tags during refetches
    removedTagNames.forEach(t => seen.add(t));

    const addTag = (tag?: string | null) => {
      if (tag == null) return;
      const normalized = String(tag).trim();
      if (!normalized) return;
      const lower = normalized.toLowerCase();
      if (seen.has(lower)) return;
      seen.add(lower);
      tags.push(normalized);
    };

    if (Array.isArray(details?.tags)) {
      details?.tags.forEach(addTag);
    }
    if (Array.isArray(mod?.tags)) {
      mod?.tags.forEach(addTag);
    }
    return tags;
  }, [details, mod, customTags, removedTagNames]);

  const appliedTagNames = useMemo(() => {
    const names = new Set<string>();
    overviewTags.forEach(t => names.add(t.toLowerCase().trim()));
    if (Array.isArray(customTags)) {
      customTags.forEach(ct => {
        if (ct?.tag) {
          names.add(ct.tag.toLowerCase().trim());
        }
      });
    }
    return names;
  }, [overviewTags, customTags]);

  /**
   * What to search Nexus with when looking for artwork of this character.
   *
   * Seeded from the mod's *name*, not its character tag. Authors name mods
   * "<skin> <character>" — "LunaSnow AbyssalGlow Symbiote" — so the name
   * carries the skin, which the tag does not. Searching the tag alone found
   * the right hero wearing the wrong outfit every time.
   *
   * Stripped of the noise that never appears in another author's title:
   * parenthetical asides like "(support+content)", version tags, and a short
   * list of flavour adjectives.
   */
  const characterSearchSeed = useMemo(() => {
    const noise = new Set([
      "sexy", "hot", "nsfw", "18+", "adult", "hd", "4k", "8k", "uhd",
      "remastered", "redux", "fix", "fixed", "update", "updated", "new",
      "mod", "skin", "replacer", "replacement", "optional", "support",
      "content", "free", "alt", "variant", "version",
    ]);
    const raw = String(mod?.name ?? "");
    const cleaned = raw
      .replace(/\([^)]*\)/g, " ") // "(support+content)"
      .replace(/\[[^\]]*\]/g, " ")
      .replace(/\bv?\d+(\.\d+)*\b/g, " ") // v1.2, 2099 stays only if wordy
      .replace(/[_\-+]+/g, " ")
      .split(/\s+/)
      .map((word) => word.trim())
      .filter((word) => word.length > 1 && !noise.has(word.toLowerCase()));

    if (cleaned.length > 0) return cleaned.join(" ");

    // Nothing left worth searching — fall back to the character tag.
    const skip = new Set([
      "characters", "ui", "audio", "animation", "misc", "miscellaneous",
      "gameplay", "skins", "nsfw", "adult", "18+",
    ]);
    const candidates = [
      ...customTags.map((t) => t?.tag).filter(Boolean),
      ...overviewTags,
    ];
    const found = candidates.find(
      (t) => t && !skip.has(String(t).toLowerCase().trim()),
    );
    return String(found ?? "").trim();
  }, [customTags, overviewTags, mod?.name]);

  // Seeded per mod, and only when untouched, so reopening does not wipe a term
  // the user typed themselves.
  useEffect(() => {
    setNexusSearchInput(characterSearchSeed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveModId, characterSearchSeed]);

  useEffect(() => {
    let cancelled = false;
    // Cleared up front, not just on success: these belong to whichever mod was
    // open before, and a failed load would otherwise leave them on screen.
    setArchivePickerOpen(false);
    setArchiveImages([]);
    setArchiveSelection(new Set());
    setNexusSearchOpen(false);
    setNexusResults([]);
    setNexusSelection(new Set());

    async function loadDetails() {
      // Allow fetching images if we have an effective ID (even synthetic)
      if (!effectiveModId) {
        setDetails(null);
        setChangelogs(null);
        setModImages([]);
        return;
      }
      try {
        const promises: Promise<any>[] = [];
        // Use effectiveModId for fetching details (works for both Nexus and local mods)
        if (effectiveModId) {
          promises.push(getModDetails(effectiveModId));
          promises.push(getModChangelogs(effectiveModId));
        } else {
          promises.push(Promise.resolve(null));
          promises.push(Promise.resolve(null));
        }
        promises.push(fetchModImagesDetailed(effectiveModId));

        const [d, c, images] = await Promise.all(promises);
        const debugInfo = {
          hasDescription: !!d?.mod?.description,
          descriptionLength: d?.mod?.description?.length || 0,
          hasSummary: !!d?.mod?.summary,
          changelogsCount: c?.length || 0,
          imagesCount: images?.length || 0,
          modKeys: d?.mod ? Object.keys(d.mod) : [],
        };
        console.log(
          "[ModModal] Loaded details for mod",
          serverModId,
          debugInfo,
        );
        try {
          const { getBaseUrl } = await import("../lib/api");
          const baseUrl = await getBaseUrl();
          await fetch(`${baseUrl}/api/debug/log`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              message: `ModModal loaded details for mod ${serverModId}`,
              data: debugInfo,
              level: "INFO",
            }),
          });
        } catch (e) {
          // Ignore debug logging errors
        }
        if (!cancelled) {
          setDetails(d);
          setChangelogs(c);
          setModImages(images?.images ?? []);
          setNexusImageIsHidden(Boolean(images?.nexusHidden));
        }
      } catch (error) {
        console.error("[ModModal] Error loading details:", error);
        if (!cancelled) {
          setDetails(null);
          setChangelogs(null);
          setModImages([]);
          setNexusImageIsHidden(false);
        }
      }
    }
    loadDetails();
    return () => {
      cancelled = true;
    };
  }, [serverModId, effectiveModId, isOpen]);

  // Load custom tags for this mod and all-tag suggestions when modal opens
  useEffect(() => {
    let cancelled = false;
    async function loadCustomTags() {
      if (!isOpen || !effectiveModId) {
        setCustomTags([]);
        setHiddenTags([]);
        setRemovedTagNames(new Set());
        return;
      }
      try {
        setRemovedTagNames(new Set());
        const [tags, allTags, hidden] = await Promise.all([
          getModCustomTags(effectiveModId),
          getAllCustomTags(),
          // Suppressed tags are already filtered out of the mod payload, so the
          // modal has to ask for them explicitly to offer them back.
          getModHiddenTags(effectiveModId).catch(() => [] as string[]),
        ]);
        if (!cancelled) {
          setCustomTags(tags);
          setAllTagSuggestions(allTags);
          setHiddenTags(hidden);
        }
      } catch (err) {
        console.warn("[ModModal] Failed to load custom tags", err);
      }
    }
    loadCustomTags();
    return () => { cancelled = true; };
  }, [isOpen, effectiveModId]);

  // Close tag dropdown on outside click
  useEffect(() => {
    if (!isTagDropdownOpen) return;
    function handleOutsideClick(e: MouseEvent) {
      if (
        tagDropdownRef.current &&
        !tagDropdownRef.current.contains(e.target as Node)
      ) {
        setIsTagDropdownOpen(false);
        setTagSearchValue("");
      }
    }
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, [isTagDropdownOpen]);

  const hydrateDownloads = useCallback(
    async (options?: { skipScan?: boolean }) => {
      if (!downloadIds.length) {
        return [] as DownloadEntry[];
      }
      if (!options?.skipScan) {
        try {
          await scanActive();
        } catch (error) {
          console.warn("[mod-modal] scanActive failed", error);
        }
      }
      const downloads = await Promise.all(
        downloadIds.map(async (rawId) => {
          try {
            const dl = await getLocalDownload(Number(rawId));
            return {
              id: dl.id,
              path: dl.path,
              contents: Array.isArray(dl.contents) ? dl.contents : [],
              hidden_contents: Array.isArray(dl.hidden_contents)
                ? dl.hidden_contents
                : [],
              active_paks: Array.isArray(dl.active_paks) ? dl.active_paks : [],
              version:
                dl.version ??
                mod?.installedVersion ??
                mod?.version ??
                mod?.latestVersion ??
                null,
              created_at: dl.created_at ?? null,
              name: dl.name ?? null,
              local_version_key: dl.local_version_key ?? null,
              latest_version: dl.latest_version ?? null,
              latest_version_key: dl.latest_version_key ?? null,
              latest_file_id: dl.latest_file_id ?? null,
              needs_update: dl.needs_update ?? false,
              mod_id: dl.mod_id ?? null,
              source_file_ids: dl.source_file_ids ?? (dl.latest_file_id ? [dl.latest_file_id] : []),
            } as DownloadEntry;
          } catch (error) {
            console.warn(
              "[mod-modal] failed to fetch local download",
              rawId,
              error,
            );
            return null;
          }
        }),
      );
      const valid = downloads.filter((d): d is DownloadEntry => Boolean(d));
      const idOrder = new Map<number, number>();
      downloadIds.forEach((rawId, index) => {
        const asNumber = Number(rawId);
        if (Number.isFinite(asNumber)) {
          idOrder.set(asNumber, index);
        }
      });
      valid.sort((a, b) => {
        const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
        const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
        if (aTime !== bTime) {
          return bTime - aTime;
        }
        const aIndex = idOrder.get(a.id) ?? Number.MAX_SAFE_INTEGER;
        const bIndex = idOrder.get(b.id) ?? Number.MAX_SAFE_INTEGER;
        if (aIndex !== bIndex) {
          return aIndex - bIndex;
        }
        return a.id - b.id;
      });
      return valid;
    },
    [downloadIds, mod?.installedVersion, mod?.version, mod?.latestVersion],
  );

  const fetchPakStatuses = useCallback(async () => {
    if (!isOpen) {
      return {} as Record<number, Record<string, ApiPakVersionStatus>>;
    }
    const request: {
      modId?: number;
      downloadIds?: number[];
    } = {};
    if (serverModId != null) {
      request.modId = serverModId;
    }
    if (downloadIds.length > 0) {
      request.downloadIds = downloadIds;
    }
    if (!request.modId && !request.downloadIds) {
      return {} as Record<number, Record<string, ApiPakVersionStatus>>;
    }
    try {
      const response = await getPakVersionStatus(request);
      const lookup: Record<number, Record<string, ApiPakVersionStatus>> = {};
      for (const entry of response) {
        const downloadId = entry.local_download_id;
        const pakKey = toBasename(entry.pak_name || "").toLowerCase();
        if (!downloadId || !pakKey) {
          continue;
        }
        if (!lookup[downloadId]) {
          lookup[downloadId] = {};
        }
        lookup[downloadId][pakKey] = entry;
      }
      return lookup;
    } catch (error) {
      console.warn("[mod-modal] failed to fetch pak version status", error);
      return {} as Record<number, Record<string, ApiPakVersionStatus>>;
    }
  }, [downloadIds, isOpen, serverModId]);

  useEffect(() => {
    let cancelled = false;
    async function loadDownloads() {
      if (!mod || !downloadIds.length) {
        setDownloadEntries([]);
        setActiveByDownload({});
        setPakStatusByDownload({});
        return;
      }
      const entries = await hydrateDownloads();
      if (!cancelled) {
        setDownloadEntries(entries);
        setActiveByDownload(toActiveMap(entries));
      }
    }
    loadDownloads();
    return () => {
      cancelled = true;
    };
  }, [hydrateDownloads, isOpen, mod, downloadIds.length]);

  useEffect(() => {
    let cancelled = false;
    async function loadStatuses() {
      const lookup = await fetchPakStatuses();
      if (!cancelled) {
        setPakStatusByDownload(lookup);
      }
    }
    loadStatuses();
    return () => {
      cancelled = true;
    };
  }, [fetchPakStatuses]);

  useEffect(() => {
    let cancelled = false;
    async function loadPakAssets() {
      if (!mod || !downloadIds.length) {
        setPakAssets([]);
        return;
      }
      try {
        const assets = await getPakAssets(downloadIds);
        if (!cancelled) {
          setPakAssets(assets);
        }
      } catch (error) {
        console.error("[ModModal] Error loading pak assets:", error);
        if (!cancelled) {
          setPakAssets([]);
        }
      }
    }
    loadPakAssets();
    return () => {
      cancelled = true;
    };
  }, [downloadIds, isOpen, mod]);

  const downloadSections = useMemo(
    () =>
      downloadEntries
        .map((entry) => ({
          entry,
          groups: groupPakEntries(entry.contents),
        }))
        .sort((a, b) => {
          const aNeedsUpdate =
            a.entry.needs_update &&
            a.entry.local_version_key != null &&
            a.entry.latest_version_key != null &&
            a.entry.local_version_key < a.entry.latest_version_key;
          const bNeedsUpdate =
            b.entry.needs_update &&
            b.entry.local_version_key != null &&
            b.entry.latest_version_key != null &&
            b.entry.local_version_key < b.entry.latest_version_key;

          if (aNeedsUpdate && !bNeedsUpdate) return -1;
          if (!aNeedsUpdate && bNeedsUpdate) return 1;
          return 0;
        }),
    [downloadEntries],
  );



  const handleToggle = useCallback(
    async (downloadId: number, files: string[], willCheck: boolean) => {
      const toastId = `apply-toggle-${downloadId}`;
      let statusLookup: Record<
        number,
        Record<string, ApiPakVersionStatus>
      > | null = null;
      let appliedSuccessfully = false;
      try {
        setIsApplying(true);
        const current = new Set<string>(activeByDownload[downloadId] || []);
        if (willCheck) {
          // Remove any same-basename variants already in the set
          // (only one variant can be active in ~mods since they share the same filename)
          const incomingBases = new Set(files.map((f) => toBasename(f)));
          for (const existing of [...current]) {
            if (
              incomingBases.has(toBasename(existing)) &&
              !files.includes(existing)
            ) {
              current.delete(existing);
            }
          }
          files.forEach((file) => current.add(file));
        } else {
          files.forEach((file) => current.delete(file));
        }
        const activeList = Array.from(current);
        const basenameTargets = new Set(files.map((file) => toBasename(file)));

        // Optimistically reflect the toggle state so the UI stays in sync while the request runs
        setActiveByDownload((prev) => {
          const next: Record<number, string[]> = {
            ...prev,
            [downloadId]: activeList,
          };
          if (willCheck && basenameTargets.size > 0) {
            for (const [key, value] of Object.entries(prev)) {
              const otherId = Number(key);
              if (otherId === downloadId) continue;
              if (!Array.isArray(value) || value.length === 0) continue;
              const filtered = value.filter(
                (name) => !basenameTargets.has(toBasename(name)),
              );
              if (filtered.length !== value.length) {
                next[otherId] = filtered;
              }
            }
          }
          return next;
        });

        setDownloadEntries((prev) =>
          prev.map((entry) => {
            if (entry.id === downloadId) {
              return { ...entry, active_paks: activeList };
            }
            if (willCheck && basenameTargets.size > 0) {
              const prevActive = Array.isArray(entry.active_paks)
                ? entry.active_paks
                : [];
              if (prevActive.length === 0) return entry;
              const filtered = prevActive.filter(
                (name) => !basenameTargets.has(toBasename(name)),
              );
              if (filtered.length !== prevActive.length) {
                return { ...entry, active_paks: filtered };
              }
            }
            return entry;
          }),
        );

        toast.loading("Applying...", { id: toastId });
        await setActivePaks(Number(downloadId), activeList);
        appliedSuccessfully = true;
        await scanActive();
        try {
          await refreshConflicts();
        } catch (refreshError) {
          console.warn("[mod-modal] refreshConflicts failed", refreshError);
        }
        const refreshed = await hydrateDownloads({ skipScan: true });
        setDownloadEntries(refreshed);
        setActiveByDownload(toActiveMap(refreshed));
        statusLookup = await fetchPakStatuses();
        toast.success(willCheck ? "Activated file" : "Deactivated file", {
          id: toastId,
          duration: 2000,
        });
      } catch (error) {
        toast.error((error as any)?.message || "Failed to apply");
        try {
          const fallback = await hydrateDownloads();
          setDownloadEntries(fallback);
          setActiveByDownload(toActiveMap(fallback));
          statusLookup = await fetchPakStatuses();
        } catch (err) {
          console.error("[mod-modal] failed to rehydrate downloads", err);
        }
      } finally {
        if (statusLookup) {
          setPakStatusByDownload(statusLookup);
        }
        setIsApplying(false);
        if (appliedSuccessfully) {
          onConflictStateChanged?.();
          // Trigger parent refresh to update mod list
          onRefresh?.();
        }
      }
    },
    [
      activeByDownload,
      fetchPakStatuses,
      hydrateDownloads,
      onConflictStateChanged,
    ],
  );

  const handleDeleteDownload = useCallback(
    async (entry: DownloadEntry): Promise<boolean> => {
      if (!entry) {
        return false;
      }
      if (isApplying && deletingDownloadId == null) {
        toast.warning("Please wait for the current operation to finish.");
        return false;
      }
      if (deletingDownloadId != null && deletingDownloadId !== entry.id) {
        toast.warning("Please wait for the current deletion to finish.");
        return false;
      }

      const downloadId = entry.id;
      const displayName = getDownloadDisplayName(entry);
      const toastId = `delete-download-${downloadId}`;
      setDeletingDownloadId(downloadId);
      setIsApplying(true);

      let success = false;
      try {
        // Step 1: Deactivate all active paks first if any are active
        const activePaks =
          activeByDownload[downloadId] ?? entry.active_paks ?? [];
        if (activePaks.length > 0) {
          toast.loading(`Deactivating ${displayName}…`, { id: toastId });
          try {
            await setActivePaks(downloadId, []);
            await scanActive();
            // Update local state to reflect deactivation
            setActiveByDownload((prev) => ({
              ...prev,
              [downloadId]: [],
            }));
            setDownloadEntries((prev) =>
              prev.map((e) =>
                e.id === downloadId ? { ...e, active_paks: [] } : e,
              ),
            );
          } catch (deactivateError) {
            console.warn(
              "[mod-modal] Failed to deactivate paks before deletion",
              deactivateError,
            );
            // Continue with deletion even if deactivation fails
          }
        }

        // Step 2: Delete the mod
        toast.loading(`Deleting ${displayName}…`, { id: toastId });
        const backendModId =
          typeof mod?.backendModId === "number" &&
          Number.isFinite(mod.backendModId)
            ? mod.backendModId
            : undefined;
        await deleteLocalDownloads([downloadId], backendModId);
        await scanActive();
        try {
          await refreshConflicts();
        } catch (refreshError) {
          console.warn(
            "[mod-modal] refreshConflicts after delete failed",
            refreshError,
          );
        }
        const refreshed = await hydrateDownloads({ skipScan: true });
        setDownloadEntries(refreshed);
        setActiveByDownload(toActiveMap(refreshed));
        const lookup = await fetchPakStatuses();
        setPakStatusByDownload(lookup);
        toast.success(`Deleted ${displayName}`, {
          id: toastId,
          duration: 2000,
        });
        onConflictStateChanged?.();
        onRefresh?.();
        success = true;
      } catch (error) {
        const message =
          error instanceof Error && error.message
            ? error.message
            : String(error ?? "Unknown error");
        toast.error(`Failed to delete ${displayName}: ${message}`, {
          id: toastId,
          duration: 4000,
        });
      } finally {
        setDeletingDownloadId(null);
        setIsApplying(false);
      }
      return success;
    },
    [
      activeByDownload,
      deletingDownloadId,
      fetchPakStatuses,
      hydrateDownloads,
      isApplying,
      mod?.backendModId,
      onConflictStateChanged,
      onRefresh,
    ],
  );

  const handleDeleteDialogChange = useCallback(
    (open: boolean) => {
      if (open) {
        return;
      }
      if (deletingDownloadId != null) {
        return;
      }
      setDeleteDialogEntry(null);
    },
    [deletingDownloadId],
  );

  const handleConfirmDelete = useCallback(async () => {
    if (!deleteDialogEntry) {
      return;
    }
    const result = await handleDeleteDownload(deleteDialogEntry);
    if (result) {
      setDeleteDialogEntry(null);
    }
  }, [deleteDialogEntry, handleDeleteDownload]);

  // Image handlers
  const uploadFiles = useCallback(
    async (fileArray: File[]) => {
      if (!effectiveModId || fileArray.length === 0) return;

      setIsUploadingImages(true);
      const toastId = toast.loading(`Uploading ${fileArray.length} image(s)...`);

      try {
        await uploadModImages(effectiveModId, fileArray);

        // Refresh images
        const updatedImages = await fetchModImages(effectiveModId);
        setModImages(updatedImages);

        toast.success(`Uploaded ${fileArray.length} image(s) successfully`, {
          id: toastId,
          duration: 2000,
        });

        // Refresh the mod list to update the card image
        if (onRefresh) {
          onRefresh();
        }
      } catch (error) {
        toast.error((error as any)?.message || "Failed to upload images", {
          id: toastId,
          duration: 4000,
        });
      } finally {
        setIsUploadingImages(false);
      }
    },
    [effectiveModId, onRefresh],
  );

  const handleImageUpload = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = event.target.files;
      if (!files) return;
      await uploadFiles(Array.from(files));
      // Reset file input
      event.target.value = "";
    },
    [uploadFiles],
  );

  /** True only for a drag carrying files from outside the app. */
  const isFileDrag = (e: React.DragEvent) =>
    Array.from(e.dataTransfer?.types ?? []).includes("Files");

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    // Reordering an image is also a drag over this container. Without this the
    // "drop images here" overlay appeared while dragging a thumbnail around.
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current += 1;
    if (dragCounterRef.current === 1) {
      setIsDragging(true);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current === 0) {
      setIsDragging(false);
    }
  }, []);

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounterRef.current = 0;
      setIsDragging(false);

      const droppedFiles = e.dataTransfer.files;
      if (!droppedFiles || droppedFiles.length === 0) return;

      // Filter to image files only
      const imageFiles = Array.from(droppedFiles).filter((f) =>
        f.type.startsWith("image/"),
      );
      if (imageFiles.length === 0) {
        toast.error("Please drop image files only.");
        return;
      }
      await uploadFiles(imageFiles);
    },
    [uploadFiles],
  );

  // Tauri native file drop listener for Images tab
  useEffect(() => {
    if (!isOpen || currentTab !== "images") return;

    let unlistenFn: (() => void) | undefined;
    let isCancelled = false;

    const setupListener = async () => {
      try {
        const { getCurrentWebview } = await import("@tauri-apps/api/webview");
        const webview = getCurrentWebview();
        const unlisten = await webview.onDragDropEvent(async (event) => {
          if (isCancelled) return;
          if (event.payload.type === "enter") {
            setIsDragging(true);
          } else if (event.payload.type === "leave") {
            setIsDragging(false);
          } else if (event.payload.type === "drop") {
            setIsDragging(false);
            const paths = event.payload.paths;
            if (paths && paths.length > 0) {
              const imageExtensions = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"];
              const imagePaths = paths.filter((path) => {
                const lower = path.toLowerCase();
                return imageExtensions.some((ext) => lower.endsWith(ext));
              });

              if (imagePaths.length === 0) {
                toast.error("Please drop image files only.");
                return;
              }

              if (!effectiveModId) return;

              setIsUploadingImages(true);
              const toastId = toast.loading(`Uploading ${imagePaths.length} image(s)...`);

              try {
                await uploadModImagesByPath(effectiveModId, imagePaths);

                // Refresh images
                const updatedImages = await fetchModImages(effectiveModId);
                setModImages(updatedImages);

                toast.success(`Uploaded ${imagePaths.length} image(s) successfully`, {
                  id: toastId,
                  duration: 2000,
                });

                if (onRefresh) {
                  onRefresh();
                }
              } catch (error) {
                toast.error((error as any)?.message || "Failed to upload images", {
                  id: toastId,
                  duration: 4000,
                });
              } finally {
                setIsUploadingImages(false);
              }
            }
          }
        });

        if (isCancelled) {
          unlisten();
        } else {
          unlistenFn = unlisten;
        }
      } catch (err) {
        console.error("Failed to setup image file drop listener:", err);
      }
    };

    setupListener();

    return () => {
      isCancelled = true;
      if (unlistenFn) unlistenFn();
      setIsDragging(false);
    };
  }, [isOpen, currentTab, effectiveModId, onRefresh]);

  const openLightbox = useCallback((index: number) => {
    setLightboxIndex(index);
    setLightboxOpen(true);
  }, []);

  const closeLightbox = useCallback(() => {
    setLightboxOpen(false);
  }, []);

  const nextImage = useCallback(() => {
    setLightboxIndex((prev) => (prev + 1) % modImages.length);
  }, [modImages.length]);

  const prevImage = useCallback(() => {
    setLightboxIndex(
      (prev) => (prev - 1 + modImages.length) % modImages.length,
    );
  }, [modImages.length]);

  // Keyboard navigation for lightbox
  useEffect(() => {
    if (!lightboxOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        closeLightbox();
      } else if (e.key === "ArrowRight") {
        nextImage();
      } else if (e.key === "ArrowLeft") {
        prevImage();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [lightboxOpen, closeLightbox, nextImage, prevImage]);

  const handleDeleteImage = useCallback(
    async (imageId: number, event: React.MouseEvent) => {
      event.stopPropagation(); // Prevent opening lightbox

      const toastId = toast.loading("Deleting image...");
      try {
        await deleteModImage(imageId);

        // Update local state
        setModImages((prev) => prev.filter((img) => img.id !== imageId));

        toast.success("Image deleted successfully", {
          id: toastId,
          duration: 2000,
        });

        // Refresh the mod list to update the card image
        if (onRefresh) {
          onRefresh();
        }
      } catch (error) {
        toast.error((error as any)?.message || "Failed to delete image", {
          id: toastId,
          duration: 4000,
        });
      }
    },
    [onRefresh],
  );

  const handleEditDescription = useCallback(() => {
    if (!mod && !details?.mod) return;
    const current =
      details?.mod?.description_bbcode || details?.mod?.description || "";
    setEditDescriptionValue(current);
    setIsEditingDescription(true);
    // Auto-detect if it looks like BBCode or if we have explicit BBCode content
    if (
      details?.mod?.description_bbcode ||
      /\[(b|i|u|url|img|color|size|font|center|quote)/i.test(current)
    ) {
      setIsBBCodeMode(true);
    } else {
      setIsBBCodeMode(false);
    }
  }, [mod, details]);

  const handleSaveDescription = useCallback(async () => {
    if (!effectiveModId) return;
    setIsSavingDescription(true);
    try {
      await updateModDetails(effectiveModId, {
        description: editDescriptionValue,
      });

      // Refetch details from server to ensure UI matches what was actually saved
      // (backend does HTML escaping and newline conversion)
      const freshDetails = await getModDetails(effectiveModId);
      setDetails(freshDetails);

      setIsEditingDescription(false);
      toast.success("Description updated");
    } catch (e) {
      console.error("Failed to save description", e);
      toast.error("Failed to save description");
    } finally {
      setIsSavingDescription(false);
    }
  }, [effectiveModId, editDescriptionValue]);

  const handleCancelEditDescription = useCallback(() => {
    setIsEditingDescription(false);
    setEditDescriptionValue("");
  }, []);

  const handleAddCustomTag = useCallback(
    async (tag: string) => {
      if (!effectiveModId || isAddingTag) return;
      const trimmed = tag.trim();
      if (!trimmed) return;
      // Prevent adding a tag that already exists on this mod (case-insensitive)
      const alreadyExists = customTags.some(
        (ct) => ct.tag.toLowerCase() === trimmed.toLowerCase(),
      );
      if (alreadyExists) {
        setIsTagDropdownOpen(false);
        setTagSearchValue("");
        return;
      }
      setIsAddingTag(true);
      try {
        const created = await addModCustomTag(effectiveModId, trimmed);
        setCustomTags((prev) => [...prev, created]);
        // Update suggestions list with the new tag if it's not already there
        setAllTagSuggestions((prev) =>
          prev.some((t) => t.toLowerCase() === trimmed.toLowerCase())
            ? prev
            : [...prev, trimmed].sort((a, b) =>
                a.toLowerCase().localeCompare(b.toLowerCase()),
              ),
        );
        setIsTagDropdownOpen(false);
        setTagSearchValue("");
        onRefresh?.({ skipScan: true });
        toast.success(`Tag "${trimmed}" added`);
      } catch (err) {
        toast.error((err as any)?.message || "Failed to add tag");
      } finally {
        setIsAddingTag(false);
      }
    },
    [effectiveModId, customTags, isAddingTag, onRefresh],
  );

  // Only custom images can be reordered — Nexus images are not ours to arrange,
  // and the backend stores an order per mod for the custom rows only.
  const customImageIds = useMemo(
    () => modImages.filter((i) => i.source === "custom").map((i) => i.id),
    [modImages],
  );
  const customImageCount = customImageIds.length;
  const firstCustomIndex = useMemo(
    () => modImages.findIndex((i) => i.source === "custom"),
    [modImages],
  );

  /**
   * The image this dialog's header should show.
   *
   * The header used details.mod.picture_url unconditionally, so on a mod linked
   * to Nexus the star did nothing here: the cards in Downloads and Active Mods
   * switched to the chosen image and the dialog kept showing the Nexus one, side
   * by side with the "Preview" badge that claimed otherwise.
   *
   * Precedence is deliberately the same rule the cards use: only an explicit
   * star outranks the Nexus artwork, because "first custom image" is a default
   * rather than a decision. Falling back to the first custom image here would
   * make the header disagree with the card again, just in the other direction.
   */
  const headerImageSrc = useMemo(() => {
    const starred = modImages.find((i) => i.source === "custom" && i.isPreview);
    if (starred?.data) {
      return `data:${starred.mimeType || "image/jpeg"};base64,${starred.data}`;
    }
    // Skipped when hidden, or removing the picture would leave it on display
    // right here — the one place it is largest.
    if (!nexusImageIsHidden && details?.mod?.picture_url) {
      return details.mod.picture_url;
    }
    const firstCustom = modImages.find((i) => i.source === "custom");
    if (firstCustom?.data) {
      return `data:${firstCustom.mimeType || "image/jpeg"};base64,${firstCustom.data}`;
    }
    return nexusImageIsHidden ? undefined : mod?.images?.[0];
  }, [modImages, nexusImageIsHidden, details?.mod?.picture_url, mod?.images]);

  const applyImageOrder = useCallback(
    async (ids: number[]) => {
      if (!effectiveModId) return;
      setIsReordering(true);
      try {
        await reorderModImages(effectiveModId, ids);
        setModImages(await fetchModImages(effectiveModId));
        // The mod card reads the first image, so the list has to be refreshed
        // for the new preview to show up outside this modal.
        onRefresh?.({ skipScan: true });
      } catch (err) {
        toast.error((err as any)?.message || "Failed to reorder images");
      } finally {
        setIsReordering(false);
      }
    },
    [effectiveModId, onRefresh],
  );

  const handleMoveImage = useCallback(
    async (imageId: number, delta: -1 | 1) => {
      const order = [...customImageIds];
      const from = order.indexOf(imageId);
      const to = from + delta;
      if (from < 0 || to < 0 || to >= order.length) return;
      [order[from], order[to]] = [order[to], order[from]];
      await applyImageOrder(order);
    },
    [customImageIds, applyImageOrder],
  );

  // Notes live per download, so they load with the download list rather than
  // with the mod: the same pak name under a different download is a different
  // file and must not inherit someone else's note.
  useEffect(() => {
    let cancelled = false;
    if (!isOpen || downloadIds.length === 0) {
      setFileNotes({});
      return;
    }
    (async () => {
      const loaded: Record<number, Record<string, string>> = {};
      await Promise.all(
        downloadIds.map(async (id) => {
          try {
            const notes = await getFileNotes(id);
            loaded[id] = Object.fromEntries(
              Object.entries(notes).map(([pak, value]) => [noteKey(pak), value.note]),
            );
          } catch {
            loaded[id] = {};
          }
        }),
      );
      if (!cancelled) setFileNotes(loaded);
    })();
    return () => {
      cancelled = true;
    };
  }, [isOpen, downloadIds]);

  const openNoteEditor = useCallback(
    (downloadId: number, pakName: string) => {
      setNoteTarget({ downloadId, pakName });
      setNoteDraft((fileNotes[downloadId] ?? {})[noteKey(pakName)] ?? "");
    },
    [fileNotes],
  );

  const handleSaveNote = useCallback(async () => {
    if (!noteTarget) return;
    const { downloadId, pakName } = noteTarget;
    const key = noteKey(pakName);
    setSavingNote(true);
    try {
      await setFileNote(downloadId, key, noteDraft);
      setFileNotes((prev) => {
        const forDownload = { ...(prev[downloadId] ?? {}) };
        if (noteDraft.trim()) forDownload[key] = noteDraft.trim();
        else delete forDownload[key];
        return { ...prev, [downloadId]: forDownload };
      });
      setNoteTarget(null);
    } catch (err) {
      toast.error((err as any)?.message || "Could not save that note");
    } finally {
      setSavingNote(false);
    }
  }, [noteTarget, noteDraft]);

  const handleRemoveFile = useCallback(
    async (downloadId: number, pakName: string) => {
      setRemovingFile(pakName);
      try {
        await removeDownloadFile(downloadId, pakName);
        // No longer "Rebuild Local Downloads restores it": a rebuild now leaves
        // the removal alone, and the file is listed under Hidden in this mod.
        toast.success(`Removed ${noteKey(pakName)}`, {
          description: "It moves to Hidden below — restore it there any time.",
          duration: 5000,
        });
        setHiddenOpenFor((prev) => new Set(prev).add(downloadId));
        const entries = await hydrateDownloads({ skipScan: true });
        setDownloadEntries(entries);
        onRefresh?.({ skipScan: true });
        onConflictStateChanged?.();
      } catch (err) {
        toast.error((err as any)?.message || "Failed to remove file");
      } finally {
        setRemovingFile(null);
      }
    },
    [onRefresh, onConflictStateChanged, hydrateDownloads],
  );

  /**
   * Ask before deleting from the archive, unless the user muted the question.
   *
   * The mute expires after a day rather than for good: this is the one action
   * in the app that destroys a file the user cannot get back, and a permanent
   * "don't ask again" would turn a stray click months later into a silent loss.
   */
  const performDeleteFile = useCallback(
    async (downloadId: number, pakName: string) => {
      setDeletingFile(pakName);
      try {
        const result = await deleteDownloadFile(downloadId, pakName);
        toast.success(`Deleted ${result.deleted}`, {
          description:
            result.members_removed > 1
              ? `${result.members_removed} files removed from the archive`
              : "Removed from the archive",
        });
        const entries = await hydrateDownloads({ skipScan: true });
        setDownloadEntries(entries);
        onRefresh?.({ skipScan: true });
        onConflictStateChanged?.();
      } catch (err) {
        toast.error((err as any)?.message || "Could not delete that file");
      } finally {
        setDeletingFile(null);
      }
    },
    [hydrateDownloads, onRefresh, onConflictStateChanged],
  );

  const requestDeleteFile = useCallback(
    (downloadId: number, pakName: string) => {
      let muted = false;
      try {
        const until = Number(localStorage.getItem(DELETE_PROMPT_MUTED_UNTIL) || 0);
        muted = Number.isFinite(until) && Date.now() < until;
      } catch {
        muted = false;
      }
      if (muted) {
        void performDeleteFile(downloadId, pakName);
        return;
      }
      setSuppressDeletePrompt(false);
      setDeleteFileTarget({ downloadId, pakName });
    },
    [performDeleteFile],
  );

  const confirmDeleteFile = useCallback(() => {
    if (!deleteFileTarget) return;
    if (suppressDeletePrompt) {
      try {
        localStorage.setItem(
          DELETE_PROMPT_MUTED_UNTIL,
          String(Date.now() + 24 * 60 * 60 * 1000),
        );
      } catch {
        // Private mode or a full quota: asking every time is the safe fallback.
      }
    }
    const { downloadId, pakName } = deleteFileTarget;
    setDeleteFileTarget(null);
    void performDeleteFile(downloadId, pakName);
  }, [deleteFileTarget, suppressDeletePrompt, performDeleteFile]);

  const handleRestoreFile = useCallback(
    async (downloadId: number, pakName: string) => {
      setRestoringFile(pakName);
      try {
        await restoreDownloadFile(downloadId, pakName);
        // Takes effect at once: hiding is applied when the mod is read, so
        // nothing has to be rebuilt for the file to come back.
        const entries = await hydrateDownloads({ skipScan: true });
        setDownloadEntries(entries);
        onRefresh?.({ skipScan: true });
        toast.success(`${noteKey(pakName)} is back`);
      } catch (err) {
        toast.error((err as any)?.message || "Could not restore that file");
      } finally {
        setRestoringFile(null);
      }
    },
    [hydrateDownloads, onRefresh],
  );

  /** Move the dragged image to the position of the one it was dropped on. */
  const handleDropOnImage = useCallback(
    async (draggedId: number, targetId: number) => {
      const order = [...customImageIds];
      const from = order.indexOf(draggedId);
      const to = order.indexOf(targetId);
      if (from < 0 || to < 0 || from === to) return;
      // Splice rather than swap: dragging an image across several others should
      // slide them along, not exchange two distant positions.
      order.splice(to, 0, order.splice(from, 1)[0]);
      await applyImageOrder(order);
    },
    [customImageIds, applyImageOrder],
  );

  const handleMakePreview = useCallback(
    async (imageId: number) => {
      if (!effectiveModId) return;
      setIsReordering(true);
      try {
        // One call: marks the image as the card preview AND moves it to the
        // front. Ordering alone was not enough — the card preferred the Nexus
        // picture_url, so on a linked mod the star did nothing visible.
        await setModImagePreview(effectiveModId, imageId);
        // Detailed, because starring the Nexus picture also un-hides it.
        const detail = await fetchModImagesDetailed(effectiveModId);
        setModImages(detail.images);
        setNexusImageIsHidden(detail.nexusHidden);
        onRefresh?.({ skipScan: true });
        toast.success("Preview updated");
      } catch (err) {
        toast.error((err as any)?.message || "Failed to set preview");
      } finally {
        setIsReordering(false);
      }
    },
    [effectiveModId, onRefresh],
  );

  /**
   * Offer the images the mod's own archive already contains.
   *
   * Measured over a real library: 55 of 123 archives ship preview images next
   * to the .pak files, median 9 each, and their names track the pak variants.
   * That is where the "several variants" of a mod actually live — Nexus only
   * ever publishes one picture, and its API has no gallery to ask for.
   */
  const handleFindArchiveImages = useCallback(async () => {
    const downloadId = downloadIds[0];
    if (downloadId == null) return;

    setArchiveScanning(true);
    setArchivePickerOpen(true);
    setArchiveImages([]);
    setArchiveSelection(new Set());
    try {
      const { images, reason } = await listArchiveImages(Number(downloadId));
      setArchiveImages(images);
      if (images.length === 0) {
        setArchivePickerOpen(false);
        toast.info(
          reason === "folder"
            ? "This mod is a folder, not an archive"
            : "No images found inside this mod file",
          {
            description:
              reason === "folder"
                ? "Drag images straight in instead."
                : "Not every author bundles previews. Drag your own in, or paste links below.",
          },
        );
      }
    } catch (err) {
      setArchivePickerOpen(false);
      toast.error((err as any)?.message || "Could not read the mod file");
    } finally {
      setArchiveScanning(false);
    }
  }, [downloadIds]);

  const handleImportArchiveImages = useCallback(async () => {
    const downloadId = downloadIds[0];
    if (downloadId == null || archiveSelection.size === 0) return;

    setArchiveImporting(true);
    try {
      const result = await importArchiveImages(
        Number(downloadId),
        Array.from(archiveSelection),
      );
      setArchivePickerOpen(false);
      if (effectiveModId) {
        const detail = await fetchModImagesDetailed(effectiveModId);
        setModImages(detail.images);
        setNexusImageIsHidden(detail.nexusHidden);
      }
      onRefresh?.({ skipScan: true });

      const notes: string[] = [];
      if (result.duplicates > 0) notes.push(`${result.duplicates} already added`);
      if (result.failed > 0) notes.push(`${result.failed} could not be read`);
      if (result.imported > 0) {
        toast.success(
          `Added ${result.imported} image${result.imported === 1 ? "" : "s"}`,
          { description: notes.join(" · ") || undefined },
        );
      } else {
        toast.info("Nothing new to add", {
          description: notes.join(" · ") || undefined,
        });
      }
    } catch (err) {
      toast.error((err as any)?.message || "Could not import those images");
    } finally {
      setArchiveImporting(false);
    }
  }, [downloadIds, archiveSelection, effectiveModId, onRefresh]);

  /**
   * Look for artwork of the same character on Nexus.
   *
   * The last resort for a mod with no pictures at all. The seed is the mod's own
   * character tag when there is one, because that is what actually identifies
   * the subject — the file name is usually a variant code.
   */
  const handleSearchNexusImages = useCallback(
    async (term?: string) => {
      const seed = (term ?? nexusSearchInput).trim();
      if (!seed) return;
      setNexusSearching(true);
      setNexusSearchOpen(true);
      try {
        // The backend puts this mod's own pictures first when it is linked.
        const results = await searchNexusImages(seed, 24, mod?.backendModId ?? null);
        setNexusResults(results);
        setNexusSelection(new Set());
        if (results.length === 0) {
          toast.info(`Nothing on Nexus matches "${seed}"`, {
            description: "Try the character name on its own.",
          });
        }
      } catch (err) {
        toast.error((err as any)?.message || "Could not reach Nexus");
      } finally {
        setNexusSearching(false);
      }
    },
    [nexusSearchInput, mod?.backendModId],
  );

  const handleImportNexusImages = useCallback(async () => {
    if (!effectiveModId || nexusSelection.size === 0) return;
    setIsAddingImageUrls(true);
    try {
      const result = await uploadModImagesByUrl(
        effectiveModId,
        Array.from(nexusSelection),
      );
      setNexusSearchOpen(false);
      const detail = await fetchModImagesDetailed(effectiveModId);
      setModImages(detail.images);
      setNexusImageIsHidden(detail.nexusHidden);
      onRefresh?.({ skipScan: true });
      if (result.uploaded_count > 0) {
        toast.success(
          `Added ${result.uploaded_count} image${result.uploaded_count === 1 ? "" : "s"}`,
        );
      } else {
        toast.info("Nothing new to add");
      }
    } catch (err) {
      toast.error((err as any)?.message || "Could not add those images");
    } finally {
      setIsAddingImageUrls(false);
    }
  }, [effectiveModId, nexusSelection, onRefresh]);

  const setNexusHidden = useCallback(
    async (hidden: boolean) => {
      if (!effectiveModId) return;
      setIsReordering(true);
      try {
        await setNexusImageHidden(effectiveModId, hidden);
        const detail = await fetchModImagesDetailed(effectiveModId);
        setModImages(detail.images);
        setNexusImageIsHidden(detail.nexusHidden);
        onRefresh?.({ skipScan: true });
        toast.success(hidden ? "Nexus picture removed" : "Nexus picture restored", {
          description: hidden
            ? "It stays on the mod page — Show Nexus image brings it back."
            : undefined,
        });
      } catch (err) {
        toast.error((err as any)?.message || "Could not update the Nexus picture");
      } finally {
        setIsReordering(false);
      }
    },
    [effectiveModId, onRefresh],
  );

  const handleHideNexusImage = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      void setNexusHidden(true);
    },
    [setNexusHidden],
  );

  const handleCopyGalleryHelper = useCallback(async () => {
    try {
      const { copyToClipboard } = await import("../lib/tauri-utils");
      await copyToClipboard(GALLERY_URL_SNIPPET);
      setGalleryStepsOpen(true);
      toast.success("Copied — follow the steps below", { duration: 6000 });
    } catch (err) {
      toast.error((err as any)?.message || "Could not copy to the clipboard");
    }
  }, []);

  const handleAddImagesByUrl = useCallback(async () => {
    if (!effectiveModId) return;
    const urls = imageUrlInput
      .split(/[\r\n,\s]+/)
      .map((u) => u.trim())
      .filter(Boolean);
    if (urls.length === 0) return;

    setIsAddingImageUrls(true);
    try {
      const result = await uploadModImagesByUrl(effectiveModId, urls);

      if (result.uploaded_count > 0) {
        toast.success(
          `Added ${result.uploaded_count} image${result.uploaded_count === 1 ? "" : "s"}`,
        );
        setImageUrlInput("");
        setModImages(await fetchModImages(effectiveModId));
        onRefresh?.({ skipScan: true });
      }

      // Reported individually: with several URLs pasted at once, "some failed"
      // is useless without saying which.
      if (result.failures.length > 0) {
        toast.error(
          `${result.failures.length} link${result.failures.length === 1 ? "" : "s"} could not be added`,
          {
            description: result.failures
              .slice(0, 3)
              .map((f) => `${f.url.slice(0, 40)}… — ${f.error}`)
              .join("\n"),
            duration: 10000,
          },
        );
      }
    } catch (err) {
      toast.error((err as any)?.message || "Failed to add images");
    } finally {
      setIsAddingImageUrls(false);
    }
  }, [effectiveModId, imageUrlInput, onRefresh]);

  // Auto-detected tags have no row to delete, so "removing" one records a
  // suppression the backend honours on every read. Kept separate from
  // handleRemoveCustomTag because the two are genuinely different operations:
  // one destroys user data, the other is reversible.
  const handleHideAutoTag = useCallback(
    async (tag: string) => {
      if (!effectiveModId) return;
      const normalized = tag.toLowerCase().trim();
      setRemovedTagNames((prev) => new Set(prev).add(normalized));
      try {
        await hideModTag(effectiveModId, tag);
        setHiddenTags((prev) =>
          prev.some((t) => t.toLowerCase() === normalized) ? prev : [...prev, tag],
        );
        onRefresh?.({ skipScan: true });
        toast.success(`Tag "${tag}" hidden`, {
          description: "It can be restored from Hidden tags below.",
        });
      } catch (err) {
        setRemovedTagNames((prev) => {
          const next = new Set(prev);
          next.delete(normalized);
          return next;
        });
        toast.error((err as any)?.message || "Failed to hide tag");
      }
    },
    [effectiveModId, onRefresh],
  );

  const handleUnhideAutoTag = useCallback(
    async (tag: string) => {
      if (!effectiveModId) return;
      const normalized = tag.toLowerCase().trim();
      try {
        await unhideModTag(effectiveModId, tag);
        setHiddenTags((prev) => prev.filter((t) => t.toLowerCase() !== normalized));
        setRemovedTagNames((prev) => {
          const next = new Set(prev);
          next.delete(normalized);
          return next;
        });
        onRefresh?.({ skipScan: true });
        toast.success(`Tag "${tag}" restored`);
      } catch (err) {
        toast.error((err as any)?.message || "Failed to restore tag");
      }
    },
    [effectiveModId, onRefresh],
  );

  const handleRemoveCustomTag = useCallback(
    async (tagId: number, tagName: string) => {
      if (!effectiveModId) return;
      try {
        const normalized = tagName.toLowerCase().trim();
        setRemovedTagNames((prev) => {
          const next = new Set(prev);
          next.add(normalized);
          return next;
        });
        await removeModCustomTag(effectiveModId, tagId);
        setCustomTags((prev) => prev.filter((ct) => ct.id !== tagId));
        onRefresh?.({ skipScan: true });
        toast.success(`Tag "${tagName}" removed`);
      } catch (err) {
        toast.error((err as any)?.message || "Failed to remove tag");
        const normalized = tagName.toLowerCase().trim();
        setRemovedTagNames((prev) => {
          const next = new Set(prev);
          next.delete(normalized);
          return next;
        });
      }
    },
    [effectiveModId, onRefresh],
  );

  if (!mod) return null;

  const formatNumber = (num: number) => {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
    if (num >= 1000) return (num / 1000).toFixed(1) + "K";
    return num.toString();
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  };

  // Stronger client-side sanitization using DOMPurify
  // Allow img tags and necessary attributes for BBCode-generated HTML
  // usage of USE_PROFILES: { html: true } with ADD_TAGS is the recommended way to extend defaults
  const sanitizeHtml = (html: string) =>
    DOMPurify.sanitize(html, {
      USE_PROFILES: { html: true },
      ADD_TAGS: ["img"],
      ADD_ATTR: ["target"],
    });

  const resolvedChangelogs: ApiChangelog[] = changelogs ?? [];

  const toChangelogHtml = (value?: string | null): string => {
    if (typeof value !== "string") {
      return "";
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return "";
    }
    const hasBreakTag = /<\s*br\s*\/?\s*>/i.test(trimmed);
    const normalized = hasBreakTag
      ? trimmed
      : trimmed.replace(/\r?\n/g, "<br />");
    return sanitizeHtml(normalized);
  };

  const pendingDeleteLabel = deleteDialogEntry
    ? getDownloadDisplayName(deleteDialogEntry)
    : "";
  const pendingDeletePath = deleteDialogEntry?.path ?? "";
  const isDeletingSelectedEntry =
    deleteDialogEntry != null && deletingDownloadId === deleteDialogEntry.id;

  // Compute if any pak files are currently activated across all downloads
  const hasAnyActivePaks = useMemo(() => {
    return Object.values(activeByDownload).some(
      (activePaks) => Array.isArray(activePaks) && activePaks.length > 0,
    );
  }, [activeByDownload]);

  // Comments tab removed per request

  const handleDeactivateAll = useCallback(async () => {
    if (isApplying) return;
    const activeEntries = Object.entries(activeByDownload).filter(
      ([_, active]) => Array.isArray(active) && active.length > 0
    );
    if (activeEntries.length === 0) return;

    setIsApplying(true);
    const toastId = toast.loading("Deactivating all...");
    let appliedSuccessfully = false;

    try {
      // Optimistic update
      setActiveByDownload((prev) => {
        const next = { ...prev };
        activeEntries.forEach(([id]) => {
          next[Number(id)] = [];
        });
        return next;
      });
      setDownloadEntries((prev) =>
        prev.map((entry) => {
          if (activeEntries.some(([id]) => Number(id) === entry.id)) {
            return { ...entry, active_paks: [] };
          }
          return entry;
        })
      );

      // Backend calls
      await Promise.all(
        activeEntries.map(([id]) => setActivePaks(Number(id), []))
      );
      appliedSuccessfully = true;
      await scanActive();
      try {
        await refreshConflicts();
      } catch (err) {
        console.warn("[mod-modal] refreshConflicts failed", err);
      }

      const refreshed = await hydrateDownloads({ skipScan: true });
      setDownloadEntries(refreshed);
      setActiveByDownload(toActiveMap(refreshed));
      const statusLookup = await fetchPakStatuses();
      setPakStatusByDownload(statusLookup);

      toast.success("Deactivated all mod files", {
        id: toastId,
        duration: 2000,
      });
    } catch (error) {
      toast.error((error as any)?.message || "Failed to deactivate", {
        id: toastId,
      });
      try {
        const fallback = await hydrateDownloads();
        setDownloadEntries(fallback);
        setActiveByDownload(toActiveMap(fallback));
        const statusLookup = await fetchPakStatuses();
        setPakStatusByDownload(statusLookup);
      } catch (err) {
        console.error("[mod-modal] failed to rehydrate downloads", err);
      }
    } finally {
      setIsApplying(false);
      if (appliedSuccessfully) {
        onConflictStateChanged?.();
        onRefresh?.();
      }
    }
  }, [
    activeByDownload,
    isApplying,
    hydrateDownloads,
    fetchPakStatuses,
    onConflictStateChanged,
    onRefresh,
  ]);

  // Note: we rely on local download contents for toggling, not Nexus file list.

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent
        className="!w-[1200px] !max-w-[95vw] !sm:max-w-[1200px] !md:max-w-[1200px] !lg:max-w-[1200px] !xl:max-w-[1200px] !h-[90vh] !max-h-[90vh] p-0 !flex !flex-col overflow-hidden !grid-none"
        style={{
          width: "1200px",
          maxWidth: "95vw",
          height: "90vh",
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
        }}
        aria-describedby="mod-dialog-description"
        showCloseButton={false}
      >
        <div className="flex flex-col h-full min-h-0 overflow-hidden">
          {/* Fixed save/cancel buttons for description editing */}
          {isEditingDescription && (
            <div
              style={{
                position: "absolute",
                bottom: "92px",
                left: "24px",
                display: "flex",
                alignItems: "center",
                gap: "8px",
                backgroundColor: "rgba(0, 0, 0, 0.95)",
                backdropFilter: "blur(4px)",
                padding: "8px",
                borderRadius: "6px",
                border: "1px solid rgba(255, 255, 255, 0.1)",
                boxShadow: "0 4px 6px rgba(0, 0, 0, 0.3)",
                zIndex: 100,
              }}
            >
              <Button
                variant="ghost"
                size="icon"
                onClick={handleCancelEditDescription}
                disabled={isSavingDescription}
                title="Cancel"
                className="h-8 w-8 hover:bg-destructive/10 hover:text-destructive"
              >
                <XIcon className="w-4 h-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={handleSaveDescription}
                disabled={isSavingDescription}
                title="Save"
                className="h-8 w-8 hover:bg-green-500/10 hover:text-green-600"
              >
                {isSavingDescription ? (
                  <div className="w-4 h-4 border-2 border-current border-t-transparent animate-spin rounded-full" />
                ) : (
                  <Check className="w-4 h-4 text-green-500" />
                )}
              </Button>
            </div>
          )}
          {/* Hidden description for accessibility to satisfy aria-describedby */}
          <p id="mod-dialog-description" className="sr-only">
            Manage and apply mod files for {mod?.name}.
          </p>
          {/* Header */}
          <DialogHeader className="p-6 pb-4 flex-shrink-0">
            <div className="flex items-start gap-4">
              <div className="w-24 h-24 bg-muted rounded-lg overflow-hidden flex-shrink-0">
                <img
                  src={headerImageSrc}
                  alt={mod.name}
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    const fallback =
                      "https://i.pinimg.com/1200x/44/da/5e/44da5e6d9dd75cb753ab5925aff4ce4c.jpg";
                    if (e.currentTarget.src !== fallback) {
                      e.currentTarget.src = fallback;
                    }
                  }}
                />
              </div>

              <div className="flex-1 min-w-0">
                <DialogTitle className="text-2xl mb-2">{details?.mod?.name || mod.name}</DialogTitle>
                
                {details?.mod?.status === 'under_moderation' && (
                  <div className="text-amber-500 font-medium text-sm flex items-center gap-1.5 mb-2 bg-amber-500/10 p-2 rounded-md border border-amber-500/20">
                    <AlertTriangle className="w-4 h-4" />
                    This mod is currently under moderation on Nexus Mods and cannot be synced properly.
                  </div>
                )}
                {details?.mod?.status === 'hidden' && (
                  <div className="text-amber-500 font-medium text-sm flex items-center gap-1.5 mb-2 bg-amber-500/10 p-2 rounded-md border border-amber-500/20">
                    <AlertTriangle className="w-4 h-4" />
                    This mod is currently hidden on Nexus Mods by its author.
                  </div>
                )}

                <p className="text-muted-foreground mb-3">
                  {details?.mod?.summary || mod.description || "No summary available."}
                </p>

                <div className="flex items-center gap-3 mb-3">
                  {(!mod.backendModId || mod.backendModId <= 0 || mod.needsManualModId) ? (
                    <AuthorPopover 
                      modKey={mod.modKey!} 
                      currentAuthorName={mod.customAuthorName} 
                      onSave={() => {
                        if (onRefresh) {
                          onRefresh({ skipScan: true });
                        } else {
                          window.dispatchEvent(new CustomEvent("refresh-downloads"));
                        }
                      }}
                    >
                      <div className="flex items-center gap-2 cursor-pointer hover:bg-accent hover:text-accent-foreground p-1 -ml-1 rounded-sm transition-colors group">
                        <Avatar className="w-6 h-6">
                          <AvatarImage
                            src={mod.customAuthorAvatar || mod.authorAvatar || undefined}
                            alt={mod.customAuthorName || mod.author || "Unknown author"}
                            referrerPolicy="no-referrer"
                            onError={(event: SyntheticEvent<HTMLImageElement>) => {
                              const img = event.currentTarget;
                              if (img.dataset.fallbackApplied === "1") return;
                              img.dataset.fallbackApplied = "1";
                              img.src = "";
                            }}
                          />
                          <AvatarFallback className="text-xs">
                            {(mod.customAuthorName || mod.author || "?").substring(0, 2).toUpperCase()}
                          </AvatarFallback>
                        </Avatar>
                        <span className="font-medium flex items-center gap-1 group-hover:text-primary">
                          {mod.customAuthorName || mod.author || "Assign Author"}
                          <Pencil className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity ml-1" />
                        </span>
                      </div>
                    </AuthorPopover>
                  ) : (
                    <a
                      className="flex items-center gap-2 cursor-pointer hover:text-primary transition-colors"
                      onClick={async () => {
                        const modUrl = `https://next.nexusmods.com/profile/${
                          details?.mod?.author || mod.author || "unknown"
                        }`;
                        try {
                          const { openInBrowser } =
                            await import("../lib/tauri-utils");
                          await openInBrowser(modUrl);
                        } catch (error) {
                          console.error("Failed to open mod page:", error);
                        }
                      }}
                    >
                      <Avatar className="w-6 h-6">
                        <AvatarImage
                          src={mod.authorAvatar || undefined}
                          alt={mod.author || "Unknown author"}
                          referrerPolicy="no-referrer"
                          onError={(event: SyntheticEvent<HTMLImageElement>) => {
                            const img = event.currentTarget;
                            if (img.dataset.fallbackApplied === "1") return;
                            img.dataset.fallbackApplied = "1";
                            img.src = "";
                          }}
                        />
                        <AvatarFallback className="text-xs">
                          {(mod.author?.trim()?.[0] ?? "?").toUpperCase()}
                        </AvatarFallback>
                      </Avatar>
                      <span className="font-medium">
                        {details?.mod?.author || mod.author || "Unknown author"}
                      </span>
                    </a>
                  )}
                  {mod.categoryTags && mod.categoryTags.length > 0 && (
                    <div className="flex gap-1 flex-wrap">
                      {mod.categoryTags.map((tag) => (
                        <Badge
                          key={`modal-category-${tag}`}
                          variant="secondary"
                        >
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  )}
                  {serverModId && (
                    <div className="flex gap-1 flex-wrap bg-muted rounded-md px-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={async () => {
                          const modUrl = `https://www.nexusmods.com/marvelrivals/mods/${serverModId}`;
                          try {
                            const { openInBrowser } =
                              await import("../lib/tauri-utils");
                            await openInBrowser(modUrl);
                          } catch (error) {
                            console.error("Failed to open mod page:", error);
                          }
                        }}
                        className="h-6 w-6"
                        title="View on Nexus Mods"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </Button>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-6 text-sm text-muted-foreground">
                  {mod.backendModId != null && mod.backendModId > 0 && (
                    <>
                      <div className="flex items-center gap-1">
                        <Download className="w-6 h-4" />
                        {formatNumber(
                          (details?.mod?.mod_downloads as number | null) ??
                            mod.downloads ??
                            0,
                        )}{" "}
                        downloads
                      </div>
                      <div className="flex items-center gap-1">
                        <Star className="w-6 h-4 fill-yellow-400 text-yellow-400" />
                        {details?.mod?.endorsement_count != null
                          ? `${details.mod.endorsement_count} endorsements`
                          : `${mod.rating.toFixed(1)} rating`}
                      </div>
                    </>
                  )}
                  <div className="flex items-center gap-1">
                    <Calendar className="w-6 h-4" />
                    Updated{" "}
                    {formatDate(
                      details?.latest_file?.uploaded_at || mod.lastUpdated,
                    )}
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <Button
                  variant={hasAnyActivePaks ? "default" : "secondary"}
                  onClick={() => {
                    if (hasAnyActivePaks) {
                      handleDeactivateAll();
                    } else {
                      onInstall(mod.id);
                    }
                  }}
                  className="gap-2"
                >
                  <Download className="w-4 h-4" />
                  {hasAnyActivePaks ? "Installed" : "Not Installed"}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => onFavorite(mod.id)}
                  className={`gap-2 ${mod.isFavorited ? "text-red-500" : ""}`}
                >
                  <Heart
                    className={`w-4 h-4 ${
                      mod.isFavorited ? "fill-current" : ""
                    }`}
                  />
                  {mod.isFavorited ? "Favorited" : "Add to Favorites"}
                </Button>
                {/* Always shown inside the mod, in both states.
                    The main list still only nags when an id is missing, but in
                    here the link is a fact worth seeing — and worth changing,
                    since a wrong id quietly attaches another mod's artwork and
                    changelog with no way to correct it. */}
                {mod.needsManualModId || mod.backendModId == null ? (
                  <Button
                    variant="outline"
                    className="gap-2 text-amber-400 border-amber-400/40 hover:bg-amber-400/10"
                    onClick={(e) => { e.stopPropagation(); onAssignModId?.(mod.id); }}
                  >
                    <Link className="w-4 h-4" /> Assign Mod ID
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    className="gap-2 text-emerald-400 border-emerald-400/40 hover:bg-emerald-400/10"
                    onClick={(e) => { e.stopPropagation(); onAssignModId?.(mod.id); }}
                    title="Linked to this Nexus mod — click to change"
                  >
                    <Link className="w-4 h-4" /> Mod ID: {mod.backendModId}
                  </Button>
                )}
                {mod.renameStatus === "failed" && (
                  <div className="text-xs text-red-400 flex items-center gap-1 justify-center py-1">
                    <AlertCircle className="w-3 h-3" /> {mod.renameError}
                  </div>
                )}
              </div>
            </div>
          </DialogHeader>

          <Separator className="flex-shrink-0" />

          {/* Content */}
          <div
            className="flex-1 min-h-0 overflow-y-auto custom-scrollbar"
            style={{ height: "calc(100% - 200px)" }}
          >
            <Tabs
              key={initialTab ?? "overview"}
              value={currentTab}
              onValueChange={setCurrentTab}
              className="flex flex-col"
            >
              <TabsList className="mx-6 mt-4 mb-0 flex-shrink-0">
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="images">Images</TabsTrigger>
                <TabsTrigger value="files">Files</TabsTrigger>
                <TabsTrigger value="assets">Assets</TabsTrigger>
                <TabsTrigger value="changelog">Changelog</TabsTrigger>
              </TabsList>

              <div className="pb-6">
                <TabsContent value="overview" className="m-0 data-[state=active]:block">
                    <div className="px-6 py-4">
                      <div className="space-y-6">
                        <div>
                          <h3 className="font-medium mb-3">Tags</h3>
                          <div className="flex flex-wrap gap-2 items-center">
                             {/* Auto-detected tags from Nexus/extraction.
                                 These have no row to delete, so the X records a
                                 suppression instead — reversible, and it
                                 survives re-extraction and Nexus syncs. */}
                             {overviewTags.map((tag) => (
                               <Badge
                                 key={`overview-tag-${tag}`}
                                 variant="secondary"
                                 className="text-xs gap-1 pr-1"
                               >
                                 {tag.toLowerCase()}
                                 {effectiveModId && (
                                   <button
                                     type="button"
                                     onClick={() => handleHideAutoTag(tag)}
                                     className="ml-0.5 rounded-full hover:bg-black/10 dark:hover:bg-white/10 p-0.5 transition-colors"
                                     title={`Hide tag "${tag}"`}
                                   >
                                     <X className="w-2.5 h-2.5" />
                                   </button>
                                 )}
                               </Badge>
                             ))}
 
                             {/* User-created custom tags */}
                             {customTags.map((ct) => (
                               <Badge
                                 key={`custom-tag-${ct.id}`}
                                 variant="secondary"
                                 className="text-xs gap-1 pr-1"
                               >
                                 {ct.tag.toLowerCase()}
                                 <button
                                   type="button"
                                   onClick={() =>
                                     handleRemoveCustomTag(ct.id, ct.tag)
                                   }
                                   className="ml-0.5 rounded-full hover:bg-black/10 dark:hover:bg-white/10 p-0.5 transition-colors"
                                   title={`Remove tag "${ct.tag}"`}
                                 >
                                   <X className="w-2.5 h-2.5" />
                                 </button>
                               </Badge>
                             ))}

                            {/* + Add tag button with dropdown */}
                            {effectiveModId && (
                              <div className="relative" ref={tagDropdownRef}>
                                <Badge
                                  variant="outline"
                                  className="text-xs border-dashed border-violet-500/50 text-violet-500 dark:text-violet-400 hover:border-violet-600 hover:text-violet-600 dark:hover:text-violet-300 hover:bg-violet-500/10 dark:hover:bg-violet-400/15 cursor-pointer active:scale-95 transition-all duration-150"
                                  asChild
                                >
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setIsTagDropdownOpen((v) => !v);
                                      setTagSearchValue("");
                                    }}
                                    className="flex items-center justify-center gap-1 w-full h-full bg-transparent border-none outline-none font-medium p-0 m-0"
                                    title="Add custom tag"
                                  >
                                    <Plus className="w-3 h-3 shrink-0" />
                                    <span>Add Tag</span>
                                  </button>
                                </Badge>

                                {isTagDropdownOpen && (
                                  <div
                                    className="absolute z-50 mt-1 w-56 rounded-lg border bg-popover shadow-lg overflow-hidden"
                                    style={{ top: "100%", left: 0 }}
                                  >
                                    {/* Search input */}
                                    <div className="p-2 border-b">
                                      <input
                                        autoFocus
                                        type="text"
                                        value={tagSearchValue}
                                        onChange={(e) =>
                                          setTagSearchValue(e.target.value)
                                        }
                                        onKeyDown={(e) => {
                                          if (e.key === "Escape") {
                                            setIsTagDropdownOpen(false);
                                            setTagSearchValue("");
                                          }
                                          if (e.key === "Enter" && tagSearchValue.trim()) {
                                            handleAddCustomTag(tagSearchValue.trim());
                                          }
                                        }}
                                        placeholder="Search or create tag..."
                                        className="w-full text-xs px-2 py-1.5 rounded-md border bg-background outline-none focus:ring-1 focus:ring-primary"
                                      />
                                    </div>

                                    {/* Tag list */}
                                    <div 
                                      className="overflow-y-auto custom-scrollbar py-1"
                                      style={{ maxHeight: "12rem" }}
                                    >
                                      {/* "Create new" option */}
                                      {tagSearchValue.trim() &&
                                        !allTagSuggestions.some(
                                          (t) =>
                                            t.toLowerCase() ===
                                            tagSearchValue.trim().toLowerCase(),
                                        ) && (
                                          <button
                                            type="button"
                                            disabled={isAddingTag}
                                            onClick={() =>
                                              handleAddCustomTag(
                                                tagSearchValue.trim(),
                                              )
                                            }
                                            className="w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-accent transition-colors text-primary"
                                          >
                                            <Plus className="w-3 h-3 shrink-0" />
                                            Create&nbsp;
                                            <span className="font-semibold truncate">
                                              "{tagSearchValue.trim().toLowerCase()}"
                                            </span>
                                          </button>
                                        )}

                                      {/* Filtered existing suggestions */}
                                      {(() => {
                                        const filtered = allTagSuggestions.filter((t) =>
                                          t
                                            .toLowerCase()
                                            .includes(tagSearchValue.toLowerCase()) &&
                                          !appliedTagNames.has(t.toLowerCase().trim())
                                        );

                                        return (
                                          <>
                                            {filtered.slice(0, 50).map((suggestion) => (
                                              <button
                                                key={`suggestion-${suggestion}`}
                                                type="button"
                                                disabled={isAddingTag}
                                                onClick={() => handleAddCustomTag(suggestion)}
                                                className="w-full text-left px-3 py-2 text-xs flex items-center justify-between gap-2 hover:bg-accent cursor-pointer transition-colors"
                                              >
                                                <span className="truncate">{suggestion.toLowerCase()}</span>
                                              </button>
                                            ))}
                                            {filtered.length > 50 && (
                                              <div className="px-3 py-1.5 text-[10px] text-muted-foreground text-center bg-muted/20 border-t sticky bottom-0">
                                                Showing top 50 of {filtered.length} tags. Type to refine.
                                              </div>
                                            )}
                                          </>
                                        );
                                      })()}

                                      {/* Empty state */}
                                      {allTagSuggestions.filter((t) =>
                                        t
                                          .toLowerCase()
                                          .includes(tagSearchValue.toLowerCase()) &&
                                        !appliedTagNames.has(t.toLowerCase().trim())
                                      ).length === 0 &&
                                        !tagSearchValue.trim() && (
                                          <p className="text-xs text-muted-foreground text-center py-3 px-3">
                                            Type to create your first tag
                                          </p>
                                        )}
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Fallback: no tags at all */}
                            {overviewTags.length === 0 &&
                              customTags.length === 0 &&
                              !effectiveModId && (
                                <p className="text-sm text-muted-foreground italic">
                                  No tags available for this mod.
                                </p>
                              )}
                          </div>

                          {/* Hiding an auto tag must not be a one-way door. */}
                          {hiddenTags.length > 0 && (
                            <div className="mt-3 pt-3 border-t border-border/50">
                              <p className="text-xs text-muted-foreground mb-2">
                                Hidden tags — click to restore
                              </p>
                              <div className="flex flex-wrap gap-2">
                                {hiddenTags.map((tag) => (
                                  <Badge
                                    key={`hidden-tag-${tag}`}
                                    variant="outline"
                                    className="text-xs gap-1 pr-1 opacity-60 hover:opacity-100 transition-opacity"
                                  >
                                    <span className="line-through">{tag.toLowerCase()}</span>
                                    <button
                                      type="button"
                                      onClick={() => handleUnhideAutoTag(tag)}
                                      className="ml-0.5 rounded-full hover:bg-black/10 dark:hover:bg-white/10 p-0.5 transition-colors"
                                      title={`Restore tag "${tag}"`}
                                    >
                                      <Plus className="w-2.5 h-2.5" />
                                    </button>
                                  </Badge>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Description */}
                        <div>
                          <div className="flex items-center justify-between mb-3">
                            <h3 className="font-medium">Description</h3>
                            <div className="flex gap-2">
                              {effectiveModId && !isEditingDescription && (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-6 w-6"
                                  onClick={handleEditDescription}
                                  title="Edit Description"
                                >
                                  <Pencil className="w-3.5 h-3.5 text-muted-foreground" />
                                </Button>
                              )}
                              {isEditingDescription && (
                                <Button
                                  variant={isBBCodeMode ? "default" : "outline"}
                                  size="sm"
                                  onClick={() => setIsBBCodeMode(!isBBCodeMode)}
                                  title="Toggle BBCode Mode"
                                  className="h-6 text-xs"
                                >
                                  BBCode
                                </Button>
                              )}
                            </div>
                          </div>

                          {isEditingDescription ? (
                            <Textarea
                              value={editDescriptionValue}
                              onChange={(e) =>
                                setEditDescriptionValue(e.target.value)
                              }
                              // Use style to force height as requested ("traditional css")
                              style={{ height: "280px", minHeight: "280px" }}
                              className="font-sans resize-y custom-scrollbar"
                              placeholder={
                                isBBCodeMode
                                  ? "Enter description in BBCode format..."
                                  : "Enter mod description..."
                              }
                            />
                          ) : (
                            <div className="prose prose-sm max-w-none text-muted-foreground">
                              {details?.mod?.description &&
                              !details.mod.description.includes(
                                "Local mod (auto-generated)",
                              ) ? (
                                <div
                                  dangerouslySetInnerHTML={{
                                    __html: sanitizeHtml(
                                      details?.mod?.description || "",
                                    ),
                                  }}
                                />
                              ) : details?.mod?.summary ? (
                                <p>{details?.mod?.summary}</p>
                              ) : (
                                <p className="italic">
                                  No description available.
                                </p>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </TabsContent>

                {/* Images Tab */}
                <TabsContent value="images" className="m-0 data-[state=active]:block">
                    <div
                      className={`px-6 py-4 min-h-[400px] transition-all duration-200 ${
                        isDragging
                          ? "bg-primary/5 border-2 border-dashed border-primary/50 rounded-xl m-2"
                          : ""
                      }`}
                      onDragEnter={handleDragEnter}
                      onDragOver={handleDragOver}
                      onDragLeave={handleDragLeave}
                      onDrop={handleDrop}
                    >
                      <div className="flex flex-wrap gap-4">
                        {/* Image thumbnails with 300px fixed height */}
                        {modImages.map((image, index) => (
                          <div
                            key={`img-${image.id}-${index}`}
                            style={{ height: "350px" }}
                            className={`bg-muted rounded-lg overflow-hidden cursor-pointer hover:opacity-80 transition-opacity relative group ${
                              dragOverId === image.id ? "ring-2 ring-primary" : ""
                            } ${draggingId === image.id ? "opacity-40" : ""}`}
                            onClick={() => openLightbox(index)}
                            // Only custom images participate: Nexus images are
                            // not ours to arrange and have no stored order.
                            draggable={image.source === "custom" && customImageCount > 1}
                            onDragStart={(e) => {
                              if (image.source !== "custom") return;
                              setDraggingId(image.id);
                              e.dataTransfer.effectAllowed = "move";
                              // Firefox refuses to start a drag without data.
                              e.dataTransfer.setData("text/plain", String(image.id));
                            }}
                            onDragEnd={() => {
                              setDraggingId(null);
                              setDragOverId(null);
                            }}
                            onDragOver={(e) => {
                              if (draggingId === null || image.source !== "custom") return;
                              e.preventDefault();
                              e.dataTransfer.dropEffect = "move";
                              if (dragOverId !== image.id) setDragOverId(image.id);
                            }}
                            onDragLeave={() => {
                              if (dragOverId === image.id) setDragOverId(null);
                            }}
                            onDrop={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              const dragged = draggingId;
                              setDraggingId(null);
                              setDragOverId(null);
                              if (dragged !== null && dragged !== image.id) {
                                void handleDropOnImage(dragged, image.id);
                              }
                            }}
                          >
                            <img
                              src={
                                image.source === "nexus"
                                  ? image.url
                                  : `data:${image.mimeType};base64,${image.data}`
                              }
                              alt={image.filename || `Image ${index + 1}`}
                              style={{ height: "100%", width: "auto" }}
                              className="object-contain"
                            />

                            {/* Every image can be removed from the list now. A
                                custom row is deleted outright; the Nexus picture
                                is only hidden, since it belongs to the mod page
                                and "Show Nexus image" below puts it back. */}
                            <button
                              className="absolute top-2 right-2 bg-destructive text-destructive-foreground rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-destructive/90"
                              onClick={(e) =>
                                image.source === "custom"
                                  ? handleDeleteImage(image.id, e)
                                  : handleHideNexusImage(e)
                              }
                              aria-label={
                                image.source === "custom"
                                  ? "Delete image"
                                  : "Remove the Nexus picture from this mod"
                              }
                              title={
                                image.source === "custom"
                                  ? "Delete image"
                                  : "Remove the Nexus picture (reversible)"
                              }
                            >
                              <X className="w-4 h-4" />
                            </button>

                            {/* Preview star, top-left and ALWAYS visible.
                                It used to appear only on hover among two other
                                icons, so there was no way to tell it existed or
                                what it did. Filled = this is the card image.

                                On every image including the Nexus one: the star
                                was custom-only, so on a downloaded mod the image
                                the app was actually showing had no star at all,
                                and there was no way back to it after choosing
                                your own. Starring it means "no custom override",
                                which the backend handles as image id 0. */}
                            <button
                              className="absolute top-2 left-2 rounded-full p-1.5 transition-colors"
                              style={{
                                background: image.isPreview
                                  ? "#a855f7"
                                  : "rgba(0,0,0,0.6)",
                                color: "white",
                              }}
                              disabled={isReordering}
                              onClick={(e) => {
                                e.stopPropagation();
                                if (!image.isPreview) void handleMakePreview(image.id);
                              }}
                              title={
                                image.isPreview
                                  ? "This image is the mod preview"
                                  : "Use as mod preview"
                              }
                              aria-label={
                                image.isPreview
                                  ? "Current mod preview"
                                  : "Use as mod preview"
                              }
                            >
                              <Star
                                className="w-4 h-4"
                                fill={image.isPreview ? "currentColor" : "none"}
                              />
                            </button>

                            {image.isPreview && (
                              <span
                                className="absolute top-2 left-11 text-xs px-2 py-1 rounded-full pointer-events-none"
                                style={{ background: "#a855f7", color: "white" }}
                              >
                                Preview
                              </span>
                            )}

                            {/* Keyboard-reachable fallback for the drag. */}
                            {image.source === "custom" && customImageCount > 1 && (
                              <div
                                className="absolute bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-1 rounded-full px-1 py-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity"
                                style={{ background: "rgba(0,0,0,0.72)" }}
                                onClick={(e) => e.stopPropagation()}
                              >
                                <button
                                  className="p-1 rounded-full text-white hover:bg-white/20 disabled:opacity-30"
                                  disabled={isReordering || index === firstCustomIndex}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void handleMoveImage(image.id, -1);
                                  }}
                                  title="Move earlier"
                                  aria-label="Move image earlier"
                                >
                                  <ChevronLeft className="w-4 h-4" />
                                </button>
                                <GripVertical className="w-4 h-4 text-white/50" />
                                <button
                                  className="p-1 rounded-full text-white hover:bg-white/20 disabled:opacity-30"
                                  disabled={isReordering || index === modImages.length - 1}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void handleMoveImage(image.id, 1);
                                  }}
                                  title="Move later"
                                  aria-label="Move image later"
                                >
                                  <ChevronRight className="w-4 h-4" />
                                </button>
                              </div>
                            )}
                          </div>
                        ))}

                        {/* Plus button for upload - enabled if we have ANY effective ID */}
                        {effectiveModId && (
                          <div
                            style={{ width: "350px", height: "350px" }}
                            className="bg-muted rounded-lg flex items-center justify-center cursor-pointer hover:bg-muted/70 transition-colors border-2 border-dashed border-border"
                          >
                            <label
                              htmlFor="image-upload"
                              className="cursor-pointer w-full h-full flex items-center justify-center"
                            >
                              <Plus className="w-12 h-12 text-muted-foreground" />
                              <input
                                id="image-upload"
                                type="file"
                                accept="image/*"
                                multiple
                                style={{ display: "none" }}
                                onChange={handleImageUpload}
                                disabled={isUploadingImages}
                              />
                            </label>
                          </div>
                        )}

                        {/* Empty state */}
                        {modImages.length === 0 && !effectiveModId && (
                          <p className="text-sm text-muted-foreground italic">
                            No images available for this mod.
                          </p>
                        )}
                      </div>

                      {/* Removing the Nexus picture only hides it, so say so and
                          offer the way back. Otherwise the delete reads as
                          permanent and nobody would risk it. */}
                      {nexusImageIsHidden && (
                        <div className="flex items-center gap-2 mt-4 text-sm text-muted-foreground">
                          <span>The mod page picture is hidden.</span>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={isReordering}
                            onClick={() => void setNexusHidden(false)}
                            className="gap-1.5"
                          >
                            <ImageIcon className="w-3.5 h-3.5" />
                            Show Nexus image
                          </Button>
                        </div>
                      )}

                      {/* Images the mod file itself ships.
                          The only reliable source of a mod's other variants:
                          Nexus publishes one picture per mod and its API has no
                          gallery, while an archive is local and cannot change
                          under us. Works for hand-made .pak drops too. */}
                      {effectiveModId && (
                        <div className="mt-6 pt-5 border-t border-border/50">
                          <div className="flex items-start justify-between gap-4 mb-2">
                            <div className="min-w-0">
                              <p className="text-sm font-medium leading-none mb-1.5">
                                From the mod file
                              </p>
                              <p className="text-xs text-muted-foreground">
                                Many mods bundle a screenshot per variant. Nothing
                                is added until you pick.
                              </p>
                            </div>
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={archiveScanning || archiveImporting}
                              onClick={() => void handleFindArchiveImages()}
                              className="gap-1.5 shrink-0"
                            >
                              {archiveScanning ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <ImageIcon className="w-3.5 h-3.5" />
                              )}
                              {archiveScanning ? "Looking…" : "Find images"}
                            </Button>
                          </div>

                          {archivePickerOpen && archiveImages.length > 0 && (
                            <div className="rounded-lg border border-border bg-muted/30 p-3">
                              <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
                                <p className="text-xs text-muted-foreground">
                                  {archiveImages.length} found ·{" "}
                                  {archiveSelection.size} selected
                                </p>
                                <div className="flex items-center gap-2">
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 text-xs"
                                    onClick={() =>
                                      setArchiveSelection(
                                        archiveSelection.size === archiveImages.length
                                          ? new Set()
                                          : new Set(archiveImages.map((i) => i.entry)),
                                      )
                                    }
                                  >
                                    {archiveSelection.size === archiveImages.length
                                      ? "Clear"
                                      : "Select all"}
                                  </Button>
                                  <Button
                                    size="sm"
                                    className="h-7 text-xs gap-1.5"
                                    disabled={archiveSelection.size === 0 || archiveImporting}
                                    onClick={() => void handleImportArchiveImages()}
                                  >
                                    {archiveImporting && (
                                      <Loader2 className="w-3 h-3 animate-spin" />
                                    )}
                                    Add {archiveSelection.size || ""}
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 w-7 p-0"
                                    onClick={() => setArchivePickerOpen(false)}
                                    aria-label="Close"
                                  >
                                    <X className="w-4 h-4" />
                                  </Button>
                                </div>
                              </div>

                              <div className="flex flex-wrap gap-2 max-h-[280px] overflow-y-auto">
                                {archiveImages.map((img) => {
                                  const picked = archiveSelection.has(img.entry);
                                  return (
                                    <button
                                      key={img.entry}
                                      type="button"
                                      onClick={() =>
                                        setArchiveSelection((prev) => {
                                          const next = new Set(prev);
                                          if (next.has(img.entry)) next.delete(img.entry);
                                          else next.add(img.entry);
                                          return next;
                                        })
                                      }
                                      className="relative rounded-md overflow-hidden border-2 transition-colors"
                                      style={{
                                        height: "110px",
                                        borderColor: picked
                                          ? "#a855f7"
                                          : "transparent",
                                      }}
                                      title={`${img.name} · ${img.width}×${img.height}`}
                                    >
                                      <img
                                        src={img.thumbnail}
                                        alt={img.name}
                                        style={{ height: "100%", width: "auto" }}
                                        className="object-contain"
                                      />
                                      {picked && (
                                        <span
                                          className="absolute top-1 right-1 rounded-full p-0.5"
                                          style={{ background: "#a855f7", color: "white" }}
                                        >
                                          <Check className="w-3 h-3" />
                                        </span>
                                      )}
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Artwork of the same character, from Nexus search.
                          Not this mod's gallery — the mod page is behind a
                          Cloudflare challenge that 403s automated requests, and
                          the search API is the reachable part. Labelled honestly
                          because it is someone else's picture of the same
                          subject. */}
                      {effectiveModId && (
                        <div className="mt-5 pt-5 border-t border-border/50">
                          <div className="flex items-start justify-between gap-4 mb-2">
                            <div className="min-w-0">
                              <p className="text-sm font-medium leading-none mb-1.5">
                                From other mods of this character
                              </p>
                              <p className="text-xs text-muted-foreground">
                                Nexus cannot hand over a mod's own gallery, so
                                this searches by name. These are other authors'
                                cover images, not pictures of your files.
                              </p>
                            </div>
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={nexusSearching || !nexusSearchInput.trim()}
                              onClick={() => void handleSearchNexusImages()}
                              className="gap-1.5 shrink-0"
                            >
                              {nexusSearching ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <Search className="w-3.5 h-3.5" />
                              )}
                              Search
                            </Button>
                          </div>
                          <input
                            value={nexusSearchInput}
                            onChange={(e) => setNexusSearchInput(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") void handleSearchNexusImages();
                            }}
                            placeholder="Character or skin name — e.g. Luna Snow"
                            className="w-full text-xs bg-background border border-border rounded-lg px-2.5 py-2"
                          />

                          {nexusSearchOpen && nexusResults.length > 0 && (
                            <div className="mt-3 rounded-lg border border-border bg-muted/30 p-3">
                              <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
                                <p className="text-xs text-muted-foreground">
                                  {nexusResults.length} found ·{" "}
                                  {nexusSelection.size} selected
                                </p>
                                <div className="flex items-center gap-2">
                                  <Button
                                    size="sm"
                                    className="h-7 text-xs gap-1.5"
                                    disabled={
                                      nexusSelection.size === 0 || isAddingImageUrls
                                    }
                                    onClick={() => void handleImportNexusImages()}
                                  >
                                    {isAddingImageUrls && (
                                      <Loader2 className="w-3 h-3 animate-spin" />
                                    )}
                                    Add {nexusSelection.size || ""}
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 w-7 p-0"
                                    onClick={() => setNexusSearchOpen(false)}
                                    aria-label="Close"
                                  >
                                    <X className="w-4 h-4" />
                                  </Button>
                                </div>
                              </div>
                              <div className="flex flex-wrap gap-2 max-h-[280px] overflow-y-auto">
                                {nexusResults.map((img) => {
                                  const picked = nexusSelection.has(img.url);
                                  return (
                                    <button
                                      key={img.url}
                                      type="button"
                                      onClick={() =>
                                        setNexusSelection((prev) => {
                                          const next = new Set(prev);
                                          if (next.has(img.url)) next.delete(img.url);
                                          else next.add(img.url);
                                          return next;
                                        })
                                      }
                                      className="relative rounded-md overflow-hidden border-2 transition-colors"
                                      style={{
                                        height: "110px",
                                        borderColor: picked ? "#a855f7" : "transparent",
                                      }}
                                      title={`${img.modName} — by ${img.author}`}
                                    >
                                      <img
                                        src={img.thumbnail}
                                        alt={img.modName}
                                        style={{ height: "100%", width: "auto" }}
                                        className="object-contain"
                                        loading="lazy"
                                      />
                                      {/* Three tiers, worth telling apart: this
                                          mod's own picture, an exact skin match,
                                          and anything found only by character. */}
                                      {img.ownMod ? (
                                        <span
                                          className="absolute bottom-1 left-1 text-[10px] px-1.5 py-0.5 rounded font-medium"
                                          style={{ background: "#22c55e", color: "#0b1f12" }}
                                        >
                                          this mod
                                        </span>
                                      ) : img.matchedTerm !== nexusSearchInput.trim() ? (
                                        <span
                                          className="absolute bottom-1 left-1 text-[10px] px-1.5 py-0.5 rounded"
                                          style={{
                                            background: "rgba(0,0,0,0.7)",
                                            color: "rgba(255,255,255,0.75)",
                                          }}
                                        >
                                          wider match
                                        </span>
                                      ) : null}
                                      {picked && (
                                        <span
                                          className="absolute top-1 right-1 rounded-full p-0.5"
                                          style={{ background: "#a855f7", color: "white" }}
                                        >
                                          <Check className="w-3 h-3" />
                                        </span>
                                      )}
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Add images by URL.
                          Nexus only ever gives this app one picture per mod:
                          the Mod type carries a single image in several sizes,
                          and the media query cannot be narrowed to a mod, so
                          there is no gallery to fetch. Pasting addresses off the
                          mod page is the way to attach the rest. */}
                      {effectiveModId && (
                        <div className="mt-5 pt-5 border-t border-border/50">
                          <div className="flex items-start justify-between gap-4 mb-2">
                            <div className="min-w-0">
                              <p className="text-sm font-medium leading-none mb-1.5">
                                From links
                              </p>
                              <p className="text-xs text-muted-foreground">
                                One address per line. To grab a whole gallery at
                                once, use the two buttons on the right.
                              </p>
                              {/* Its own line and its own colour: buried in grey
                                  body text at 12px, nobody found the one thing
                                  that explains the whole flow. */}
                              <button
                                type="button"
                                onClick={() => setGalleryStepsOpen((v) => !v)}
                                className="mt-2 inline-flex items-center gap-1 text-sm font-medium transition-opacity hover:opacity-80"
                                style={{ color: "#38bdf8" }}
                              >
                                {galleryStepsOpen ? (
                                  <ChevronDown className="w-4 h-4" />
                                ) : (
                                  <ChevronRight className="w-4 h-4" />
                                )}
                                {galleryStepsOpen ? "Hide the steps" : "Show me how"}
                              </button>
                            </div>
                            {/* Both buttons together on the right, in the order
                                they get used: open the gallery, copy addresses,
                                add them. */}
                            <div className="flex items-center gap-2 shrink-0">
                              {mod?.backendModId != null && mod.backendModId > 0 && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => {
                                    void (async () => {
                                      const { openInBrowser } = await import(
                                        "../lib/tauri-utils"
                                      );
                                      await openInBrowser(
                                        `https://www.nexusmods.com/marvelrivals/mods/${mod.backendModId}?tab=images`,
                                      );
                                    })();
                                  }}
                                  className="gap-1.5"
                                  title="Open this mod's images on Nexus, then copy the addresses"
                                >
                                  <ExternalLink className="w-3.5 h-3.5" />
                                  Open gallery
                                </Button>
                              )}
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => void handleCopyGalleryHelper()}
                                className="gap-1.5"
                                title="Copy a one-liner that collects every image address from the gallery page"
                              >
                                <ClipboardCopy className="w-3.5 h-3.5" />
                                Copy helper
                              </Button>
                              <Button
                                size="sm"
                                onClick={handleAddImagesByUrl}
                                disabled={isAddingImageUrls || !imageUrlInput.trim()}
                                className="gap-1.5"
                              >
                                {isAddingImageUrls ? (
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                ) : (
                                  <Plus className="w-3.5 h-3.5" />
                                )}
                                Add images
                              </Button>
                            </div>
                          </div>

                          {/* Written out because the console is not somewhere
                              most people go, and the browser adds a step of its
                              own the first time: Chrome refuses a pasted script
                              until you type "allow pasting". Someone who does
                              not know that just sees paste silently do nothing. */}
                          {galleryStepsOpen && (
                            <div className="mb-3 rounded-lg border border-border bg-muted/30 p-3">
                              <ol className="text-xs text-muted-foreground flex flex-col gap-1.5">
                                <li>
                                  <strong className="text-foreground">1.</strong>{" "}
                                  Press <strong className="text-foreground">Open gallery</strong> —
                                  the mod's images open in your browser.
                                </li>
                                <li>
                                  <strong className="text-foreground">2.</strong>{" "}
                                  Scroll to the bottom of that page, so every image
                                  has loaded.
                                </li>
                                <li>
                                  <strong className="text-foreground">3.</strong>{" "}
                                  Press <strong className="text-foreground">Copy helper</strong> —
                                  a short line is now on your clipboard.
                                </li>
                                <li>
                                  <strong className="text-foreground">4.</strong>{" "}
                                  In the browser press{" "}
                                  <kbd className="px-1 py-0.5 rounded bg-background border border-border font-mono">
                                    F12
                                  </kbd>{" "}
                                  and pick the{" "}
                                  <strong className="text-foreground">Console</strong> tab.
                                </li>
                                <li>
                                  <strong className="text-foreground">5.</strong>{" "}
                                  The first time, the browser asks you to type{" "}
                                  <code className="px-1 py-0.5 rounded bg-background border border-border font-mono">
                                    allow pasting
                                  </code>{" "}
                                  and press Enter. It only asks once.
                                </li>
                                <li>
                                  <strong className="text-foreground">6.</strong>{" "}
                                  Paste (
                                  <kbd className="px-1 py-0.5 rounded bg-background border border-border font-mono">
                                    Ctrl+V
                                  </kbd>
                                  ) and press Enter. Nothing appears to happen — that
                                  is correct, the addresses went to your clipboard.
                                </li>
                                <li>
                                  <strong className="text-foreground">7.</strong>{" "}
                                  Come back here, paste into the box below and press{" "}
                                  <strong className="text-foreground">Add images</strong>.
                                </li>
                              </ol>
                              <p className="text-xs text-muted-foreground/70 mt-2">
                                The app cannot read that page itself — Nexus answers
                                automated requests with a bot check. Your browser is
                                allowed to read it, so it does the reading.
                              </p>
                            </div>
                          )}

                          <textarea
                            value={imageUrlInput}
                            onChange={(e) => setImageUrlInput(e.target.value)}
                            placeholder={"https://staticdelivery.nexusmods.com/mods/…/1.png\nhttps://…/2.jpg"}
                            rows={3}
                            className="w-full text-xs font-mono bg-background border border-border rounded-lg px-2.5 py-2 resize-y"
                          />
                        </div>
                      )}
                    </div>
                  </TabsContent>

                {/* Lightbox Gallery */}
                {lightboxOpen && modImages.length > 0 && (
                  <div
                    className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center"
                    onClick={closeLightbox}
                  >
                    {/* Image counter - stays at top center of screen */}
                    <div className="absolute top-4 left-1/2 transform -translate-x-1/2 text-white text-lg font-medium z-10">
                      {lightboxIndex + 1} / {modImages.length}
                    </div>

                    {/* Image container - matches image dimensions */}
                    <div
                      className="relative inline-block"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {/* Close button - positioned on image */}
                      <button
                        className="absolute top-4 right-4 text-white hover:text-gray-300 transition-colors z-10"
                        onClick={closeLightbox}
                        aria-label="Close lightbox"
                      >
                        <X className="w-8 h-8" />
                      </button>

                      {/* Previous button - positioned on image */}
                      {modImages.length > 1 && (
                        <button
                          className="absolute left-4 top-1/2 -translate-y-1/2 text-white hover:text-gray-300 transition-colors z-10"
                          onClick={(e) => {
                            e.stopPropagation();
                            prevImage();
                          }}
                          aria-label="Previous image"
                        >
                          <ChevronLeft className="w-12 h-12" />
                        </button>
                      )}

                      {/* Image */}
                      <img
                        src={
                          modImages[lightboxIndex]?.source === "nexus"
                            ? modImages[lightboxIndex]?.url
                            : `data:${modImages[lightboxIndex]?.mimeType};base64,${modImages[lightboxIndex]?.data}`
                        }
                        alt={
                          modImages[lightboxIndex]?.filename ||
                          `Image ${lightboxIndex + 1}`
                        }
                        style={{ maxHeight: "80vh", width: "auto" }}
                        className="object-contain"
                      />

                      {/* Next button - positioned on image */}
                      {modImages.length > 1 && (
                        <button
                          className="absolute right-4 top-1/2 -translate-y-1/2 text-white hover:text-gray-300 transition-colors z-10"
                          onClick={(e) => {
                            e.stopPropagation();
                            nextImage();
                          }}
                          aria-label="Next image"
                        >
                          <ChevronRight className="w-12 h-12" />
                        </button>
                      )}
                    </div>
                  </div>
                )}

                <TabsContent value="files" className="m-0 data-[state=active]:block">
                    <div className="px-6 py-4">
                      <div className="space-y-4">
                        <div className="flex items-center gap-2 mb-4">
                          <h3 className="text-lg font-semibold flex items-center gap-2">
                            <File className="w-5 h-5" />
                            Pak Files
                          </h3>
                        </div>
                        
                        <div className="space-y-4">
                          {mod?.collectionVariants && (() => {
                            const normalizeFilename = (filename: string): string => {
                              if (!filename) return "";
                              let base = filename.split(/[/\\]/).pop() || filename;
                              base = base.toLowerCase().replace(/\.[a-z0-9]+$/i, "").trim();
                              // Strip trailing duplicate/copy suffixes (e.g., "-7", "_1", " (2)")
                              base = base.replace(/-[0-9]{1,3}$/g, "");
                              base = base.replace(/_[0-9]{1,3}$/g, "");
                              base = base.replace(/\s*\([0-9]{1,3}\)$/g, "");
                              return base.replace(/[^a-z0-9]/g, "");
                            };

                            const isVariantDownloaded = (variant: any, entry: DownloadEntry) => {
                              const fileId = variant.fileId || variant.file_id;
                              const modId = variant.file?.modId || variant.mod_id;
                              const version = variant.version;
                              const fileUri = variant.file?.uri || variant.file_uri;

                              // 1. Exact ID matches
                              if (entry.latest_file_id === fileId) return true;
                              if (entry.source_file_ids?.includes(fileId)) return true;

                              // 2. Exact Version & Mod ID matches
                              if (entry.version === version && modId != null && entry.mod_id === modId) return true;

                              // 3. Filename normalization match
                              if (entry.path && fileUri && normalizeFilename(entry.path) === normalizeFilename(fileUri)) return true;

                              // 4. Pak Status match
                              const statusMap = pakStatusByDownload[entry.id];
                              if (statusMap) {
                                return Object.values(statusMap).some(status => status.reference_file_id === fileId);
                              }

                              return false;
                            };

                            const undownloadedVariants = mod.collectionVariants.filter((variant: any) => {
                              return !downloadEntries.some(entry => isVariantDownloaded(variant, entry));
                            });
                            if (undownloadedVariants.length === 0) return null;
                            return (
                              <div className="mb-6 space-y-4">
                                <h4 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider mb-3">Missing Collection Files</h4>
                                {undownloadedVariants.map((variant: any) => {
                                  const fileId = variant.fileId || variant.file_id;
                                  const fileName = variant.file?.name || variant.file_name || 'Unknown Variant';
                                  const fileSizeInBytes = variant.file?.sizeInBytes || variant.size_in_bytes;
                                  const modId = variant.file?.modId || variant.mod_id;
                                  return (
                                    <div 
                                      key={fileId} 
                                      className="border border-border rounded-xl p-4 bg-secondary/5 space-y-3 transition-colors hover:bg-secondary/10"
                                    >
                                      <div className="flex items-center justify-between gap-3 flex-wrap">
                                        <div className="flex items-center gap-3 min-w-0">
                                          <div className="bg-primary/10 p-2 rounded-lg">
                                            <Download className="w-4 h-4 text-primary shrink-0" />
                                          </div>
                                          <div className="flex flex-col min-w-0">
                                            <span className="font-semibold text-base truncate">
                                              {fileName}
                                            </span>
                                            {fileSizeInBytes && (
                                              <span className="text-xs text-muted-foreground">
                                                {(Number(fileSizeInBytes) / 1024 / 1024).toFixed(1)} MB
                                              </span>
                                            )}
                                          </div>
                                        </div>
                                        <Button
                                          variant="default"
                                          size="sm"
                                          onClick={async () => {
                                            const game = "marvelrivals";
                                            const url = `https://www.nexusmods.com/${game}/mods/${modId}?tab=files&file_id=${fileId}&nmm=1`;
                                            try {
                                              const { openInBrowser } = await import("../lib/tauri-utils");
                                              await openInBrowser(url);
                                            } catch (error) {
                                              console.error("Failed to open Nexus download path", error);
                                            }
                                          }}
                                          className="shrink-0 font-medium"
                                        >
                                          Download Now
                                        </Button>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            );
                          })()}

                          {downloadSections.length > 0 && (
                            <h4 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider mb-2 mt-4">Downloaded Files</h4>
                          )}
                          {downloadSections.length === 0 && (!mod?.collectionVariants || (() => {
                            const normalizeFilename = (filename: string): string => {
                              if (!filename) return "";
                              let base = filename.split(/[/\\]/).pop() || filename;
                              base = base.toLowerCase().replace(/\.[a-z0-9]+$/i, "").trim();
                              // Strip trailing duplicate/copy suffixes (e.g., "-7", "_1", " (2)")
                              base = base.replace(/-[0-9]{1,3}$/g, "");
                              base = base.replace(/_[0-9]{1,3}$/g, "");
                              base = base.replace(/\s*\([0-9]{1,3}\)$/g, "");
                              return base.replace(/[^a-z0-9]/g, "");
                            };
                            const isVariantDownloaded = (variant: any, entry: DownloadEntry) => {
                              const fileId = variant.fileId || variant.file_id;
                              const modId = variant.file?.modId || variant.mod_id;
                              const version = variant.version;
                              const fileUri = variant.file?.uri || variant.file_uri;

                              if (entry.latest_file_id === fileId) return true;
                              if (entry.source_file_ids?.includes(fileId)) return true;
                              if (entry.version === version && modId != null && entry.mod_id === modId) return true;
                              if (entry.path && fileUri && normalizeFilename(entry.path) === normalizeFilename(fileUri)) return true;
                              
                              const statusMap = pakStatusByDownload[entry.id];
                              if (statusMap) {
                                return Object.values(statusMap).some(status => status.reference_file_id === fileId);
                              }
                              return false;
                            };
                            return mod.collectionVariants.filter((v: any) => !downloadEntries.some(e => isVariantDownloaded(v, e))).length === 0;
                          })()) && (
                            <div className="text-sm text-muted-foreground">
                              No local downloads recorded for this mod yet.
                            </div>
                          )}
                          {downloadSections.map(({ entry, groups }) => {
                            const activeList =
                              activeByDownload[entry.id] ??
                              entry.active_paks ??
                              [];
                            const isActive = activeList.length > 0;
                            const lower = (entry.path || "").toLowerCase();
                            const isArchive =
                              lower.endsWith(".zip") ||
                              lower.endsWith(".rar") ||
                              lower.endsWith(".7z");
                            const isSinglePak = lower.endsWith(".pak");
                            const isFolder = !isArchive && !isSinglePak;
                            const canApply =
                              isArchive || isSinglePak || isFolder;
                            const switchDisabled =
                              isApplying ||
                              deletingDownloadId === entry.id ||
                              !canApply;
                            const statusMap =
                              pakStatusByDownload[entry.id] ?? {};
                            const statusValues = Object.values(statusMap);
                            const displayVersion = normalizeVersion(
                              statusValues.find(
                                (status) =>
                                  status.display_version &&
                                  status.display_version.trim() !== "",
                              )?.display_version || entry.version,
                            );
                            let entryLabel = entry.name?.trim()
                              ? entry.name
                              : mod.name;
                            
                            if (entryLabel) {
                              entryLabel = entryLabel.replace(/\s+\d+\s+.*?\s+\d{4}\s\d{2}\s\d{2}T\d{2}\s\d{2}Z\s+[a-zA-Z0-9]+$/, '').trim();
                            }
                            return (
                              <div
                                key={entry.id}
                                className={`border border-border rounded-xl p-4 space-y-3 transition-colors ${
                                  isActive
                                    ? "bg-green-50 dark:bg-green-950/40"
                                    : "bg-background"
                                }`}
                              >
                                <div className="flex items-center justify-between gap-3 flex-wrap">
                                  <div className="flex items-center gap-3 min-w-0 flex-wrap">
                                    <h4 className="font-semibold text-base truncate">
                                      {entryLabel}
                                    </h4>
                                    <Badge
                                      variant="outline"
                                      className="text-xs"
                                    >
                                      Version {displayVersion}
                                    </Badge>
                                    <Badge
                                      variant="outline"
                                      className={`text-xs ${
                                        isActive
                                          ? "border-green-600 text-green-600"
                                          : "text-muted-foreground"
                                      }`}
                                    >
                                      {isActive ? "Active" : "Inactive"}
                                    </Badge>
                                  </div>
                                  <div className="flex items-center gap-2">
                                      {(() => {
                                          const variantNeedsUpdate =
                                            entry.needs_update &&
                                            entry.local_version_key != null &&
                                            entry.latest_version_key != null &&
                                            entry.local_version_key < entry.latest_version_key;

                                        if (!variantNeedsUpdate) return null;

                                      return (
                                        <Button
                                          variant="ghost"
                                          size="sm"
                                          onClick={() =>
                                            onUpdate?.(
                                              String(
                                                mod!.backendModId ?? mod!.id,
                                              ),
                                              entry.latest_file_id ?? undefined,
                                            )
                                          }
                                          disabled={isApplying}
                                          className="h-8 px-3 gap-1.5 text-sm font-medium bg-transparent border border-white/10 hover:bg-white hover:text-black transition-all"
                                          title={`Update to v${
                                            entry.latest_version ?? "latest"
                                          }`}
                                        >
                                          <RefreshCw className="w-3.5 h-3.5" />
                                          Update to v
                                          {entry.latest_version ?? "latest"}
                                        </Button>
                                      );
                                    })()}
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={() => {
                                        if (
                                          isApplying ||
                                          deletingDownloadId != null
                                        ) {
                                          return;
                                        }
                                        setDeleteDialogEntry(entry);
                                      }}
                                      disabled={
                                        isApplying ||
                                        deletingDownloadId === entry.id
                                      }
                                      className="text-destructive hover:text-destructive hover:bg-destructive/10"
                                      aria-label={`Delete ${entryLabel}`}
                                    >
                                      <Trash2 className="w-4 h-4" />
                                    </Button>
                                  </div>
                                </div>

                                <div className="space-y-2">
                                  {groups.length === 0 && (
                                    <div className="text-sm text-muted-foreground">
                                      No .pak files recorded for this download.
                                    </div>
                                  )}
                                  {(() => {
                                    const tree = buildFileTree(groups);
                                    const hasSubfolders = groups.some((g) =>
                                      g.primary
                                        .replace(/\\/g, "/")
                                        .includes("/"),
                                    );

                                    if (!hasSubfolders) {
                                      return groups.map(
                                        ({ primary, files }) => {
                                          const checked = files.some((file) =>
                                            activeList.includes(file),
                                          );
                                          const note =
                                            (fileNotes[entry.id] ?? {})[noteKey(primary)];
                                          return (
                                            <div
                                              key={`${entry.id}-${primary}`}
                                              className={`mod-file-item border border-border rounded-lg ${
                                                checked
                                                  ? "bg-green-100 dark:bg-green-900/60"
                                                  : "bg-popover"
                                              }`}
                                              style={{ padding: "6px" }}
                                            >
                                              <div className="flex items-center justify-between gap-4">
                                                <div className="flex items-center gap-3 min-w-0">
                                                  <File className="w-4 h-4 text-muted-foreground shrink-0" />
                                                  <div className="font-medium truncate">
                                                    {primary}
                                                  </div>
                                                </div>
                                                <div className="flex items-center gap-2 shrink-0">
                                                  <button
                                                    type="button"
                                                    onClick={() =>
                                                      openNoteEditor(entry.id, primary)
                                                    }
                                                    className={`p-1 rounded transition-colors ${
                                                      note
                                                        ? "text-amber-500 hover:bg-amber-500/10"
                                                        : "text-muted-foreground/50 hover:text-foreground hover:bg-muted"
                                                    }`}
                                                    title={note ? `Note: ${note}` : "Add a note"}
                                                    aria-label={note ? "Edit note" : "Add a note"}
                                                  >
                                                    <Pencil className="w-3.5 h-3.5" />
                                                  </button>
                                                  <Switch
                                                    disabled={switchDisabled}
                                                    checked={checked}
                                                    onCheckedChange={(
                                                      willCheck: boolean,
                                                    ) =>
                                                      handleToggle(
                                                        entry.id,
                                                        files,
                                                        willCheck,
                                                      )
                                                    }
                                                  />
                                                  {/* Eye hides, bin deletes —
                                                      see the tree renderer. */}
                                                  <button
                                                    type="button"
                                                    disabled={removingFile === primary}
                                                    onClick={() =>
                                                      void handleRemoveFile(
                                                        entry.id,
                                                        primary,
                                                      )
                                                    }
                                                    className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-40"
                                                    title={`Hide ${primary} — stays in the archive`}
                                                    aria-label={`Hide ${primary}`}
                                                  >
                                                    {removingFile === primary ? (
                                                      <Loader2 className="w-4 h-4 animate-spin" />
                                                    ) : (
                                                      <EyeOff className="w-4 h-4" />
                                                    )}
                                                  </button>
                                                  <button
                                                    type="button"
                                                    disabled={deletingFile === primary}
                                                    onClick={() =>
                                                      requestDeleteFile(entry.id, primary)
                                                    }
                                                    className="p-1 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 disabled:opacity-40"
                                                    title={`Delete ${primary} from the archive — permanent`}
                                                    aria-label={`Delete ${primary} permanently`}
                                                  >
                                                    {deletingFile === primary ? (
                                                      <Loader2 className="w-4 h-4 animate-spin" />
                                                    ) : (
                                                      <Trash2 className="w-4 h-4" />
                                                    )}
                                                  </button>
                                                </div>
                                              </div>
                                              <FileNote note={note} />
                                            </div>
                                          );
                                        },
                                      );
                                    }

                                    return (
                                      <FileTreeRenderer
                                        nodes={tree.children}
                                        depth={0}
                                        entryId={entry.id}
                                        activeList={activeList}
                                        switchDisabled={switchDisabled}
                                        handleToggle={handleToggle}
                                        removingFile={removingFile}
                                        onRemoveFile={(downloadId, pakName) =>
                                          void handleRemoveFile(downloadId, pakName)
                                        }
                                        deletingFile={deletingFile}
                                        onDeleteFile={requestDeleteFile}
                                        notes={fileNotes[entry.id] ?? {}}
                                        onEditNote={openNoteEditor}
                                      />
                                    );
                                  })()}

                                  {/* Files removed from this mod.
                                      Kept with the mod rather than in a global
                                      list in Settings: this is where you removed
                                      them and where you would look for them. */}
                                  {entry.hidden_contents.length > 0 && (
                                    <div className="mt-3 pt-3 border-t border-border/50">
                                      <button
                                        type="button"
                                        onClick={() =>
                                          setHiddenOpenFor((prev) => {
                                            const next = new Set(prev);
                                            if (next.has(entry.id)) next.delete(entry.id);
                                            else next.add(entry.id);
                                            return next;
                                          })
                                        }
                                        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                                      >
                                        {hiddenOpenFor.has(entry.id) ? (
                                          <ChevronDown className="w-3.5 h-3.5" />
                                        ) : (
                                          <ChevronRight className="w-3.5 h-3.5" />
                                        )}
                                        <EyeOff className="w-3.5 h-3.5" />
                                        Hidden ({entry.hidden_contents.length})
                                      </button>

                                      {hiddenOpenFor.has(entry.id) && (
                                        <div className="space-y-1.5 mt-2">
                                          {entry.hidden_contents.map((pak) => (
                                            <div
                                              key={`${entry.id}-hidden-${pak}`}
                                              className="flex items-center justify-between gap-3 rounded-lg bg-muted/40 px-2.5 py-1.5"
                                            >
                                              <div className="flex items-center gap-2.5 min-w-0">
                                                <File className="w-3.5 h-3.5 text-muted-foreground/60 shrink-0" />
                                                <span className="text-sm text-muted-foreground truncate">
                                                  {noteKey(pak)}
                                                </span>
                                              </div>
                                              <Button
                                                variant="ghost"
                                                size="sm"
                                                className="h-7 px-2 text-xs gap-1 shrink-0"
                                                disabled={restoringFile === pak}
                                                onClick={() =>
                                                  void handleRestoreFile(entry.id, pak)
                                                }
                                              >
                                                {restoringFile === pak ? (
                                                  <Loader2 className="w-3 h-3 animate-spin" />
                                                ) : (
                                                  <RotateCcw className="w-3 h-3" />
                                                )}
                                                Restore
                                              </Button>
                                            </div>
                                          ))}
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                </TabsContent>

                <TabsContent value="assets" className="m-0 data-[state=active]:block">
                    <div className="px-6 py-4">
                      <div className="space-y-4">
                        <div className="flex items-center gap-2 mb-4">
                          <h3 className="text-lg font-semibold flex items-center gap-2">
                            <File className="w-5 h-5" />
                            Assets
                          </h3>
                        </div>

                        {pakAssets.length === 0 && (
                          <div className="text-sm text-muted-foreground">
                            No assets found for this mod.
                          </div>
                        )}

                        {pakAssets.map((pakAsset) => (
                          <div
                            key={pakAsset.pak_name}
                            className="mod-file-item border border-border rounded-xl p-4 space-y-3 bg-background"
                          >
                            <h4 className="font-semibold text-base">
                              {pakAsset.pak_name}
                            </h4>
                            <div className="space-y-1">
                              {pakAsset.assets.length === 0 && (
                                <div className="text-sm text-muted-foreground italic">
                                  No assets in this pak
                                </div>
                              )}
                              {pakAsset.assets.map((asset, index) => (
                                <div
                                  key={`${pakAsset.pak_name}-${index}`}
                                  className="text-sm font-mono text-muted-foreground"
                                >
                                  {asset}
                                </div>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </TabsContent>

                <TabsContent value="changelog" className="m-0 data-[state=active]:block">
                    <div className="px-6 py-4">
                      <div className="space-y-4">
                        {resolvedChangelogs.map((version) => {
                          const changelogHtml = toChangelogHtml(
                            version.changelog,
                          );
                          return (
                            <div
                              key={`${version.version}-${version.uploaded_at}`}
                              className="border-l-2 border-muted pl-4"
                            >
                              <div className="flex items-center gap-2 mb-2">
                                <h4 className="font-medium">
                                  Version {version.version}
                                </h4>
                                <Badge variant="outline" className="text-xs">
                                  {version.uploaded_at
                                    ? formatDate(version.uploaded_at)
                                    : ""}
                                </Badge>
                              </div>
                              {changelogHtml ? (
                                <div
                                  className="text-sm text-muted-foreground"
                                  dangerouslySetInnerHTML={{
                                    __html: changelogHtml,
                                  }}
                                />
                              ) : (
                                <div className="text-sm text-muted-foreground italic">
                                  No changelog details provided.
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </TabsContent>

                {/* Comments tab removed per request */}
              </div>
            </Tabs>
          </div>
        </div>
        <div className="flex justify-end px-6 pb-6 pt-2">
          <DialogClose asChild>
            <Button
              variant="default"
              className="px-2 text-base font-semibold shadow-sm"
            >
              Close
            </Button>
          </DialogClose>
        </div>

        <AlertDialog
          open={deleteDialogEntry != null}
          onOpenChange={handleDeleteDialogChange}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                Delete {pendingDeleteLabel || "this download"}?
              </AlertDialogTitle>
              <AlertDialogDescription asChild>
                <div className="space-y-2 text-sm">
                  <p>
                    This removes the archive or folder from disk and deletes its
                    entry from the RivalNxt database. This action cannot be
                    undone.
                  </p>
                  {pendingDeletePath ? (
                    <p className="text-muted-foreground break-all text-xs">
                      {pendingDeletePath}
                    </p>
                  ) : null}
                </div>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={isDeletingSelectedEntry}>
                Cancel
              </AlertDialogCancel>
              <AlertDialogAction
                onClick={handleConfirmDelete}
                disabled={isDeletingSelectedEntry}
              >
                {isDeletingSelectedEntry ? "Deleting..." : "Delete"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Deleting a file out of the archive. The one action here that
            destroys something the user cannot get back, so it asks — and the
            mute it offers lasts a day, not forever. */}
        <AlertDialog
          open={deleteFileTarget != null}
          onOpenChange={(open) => {
            if (!open) setDeleteFileTarget(null);
          }}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                Delete {deleteFileTarget ? noteKey(deleteFileTarget.pakName) : ""}?
              </AlertDialogTitle>
              <AlertDialogDescription asChild>
                <div className="space-y-2 text-sm">
                  <p>
                    This removes the file from the mod's archive on disk. It
                    cannot be undone, and a rebuild will not bring it back.
                  </p>
                  <p className="text-muted-foreground">
                    To take it out of the list but keep the file, use the eye
                    icon instead.
                  </p>
                </div>
              </AlertDialogDescription>
            </AlertDialogHeader>

            <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
              <input
                type="checkbox"
                checked={suppressDeletePrompt}
                onChange={(e) => setSuppressDeletePrompt(e.target.checked)}
              />
              Don't ask again for a day
            </label>

            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={(e) => {
                  e.preventDefault();
                  confirmDeleteFile();
                }}
              >
                Delete permanently
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Per-pak note. Variants are named A_rogueVA / A_rogueVB / A_rogueVC
            and nothing in the app said what any of them changed, so telling
            them apart meant enabling one at a time. */}
        <AlertDialog
          open={noteTarget != null}
          onOpenChange={(open) => {
            if (!open && !savingNote) setNoteTarget(null);
          }}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Note</AlertDialogTitle>
              <AlertDialogDescription asChild>
                <p className="text-xs text-muted-foreground break-all font-mono">
                  {noteTarget ? noteKey(noteTarget.pakName) : ""}
                </p>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <Textarea
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              placeholder="What does this variant change? e.g. no gloves, alt colours"
              rows={4}
              maxLength={500}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  void handleSaveNote();
                }
              }}
            />
            <p className="text-xs text-muted-foreground">
              Leave it empty to remove the note. Ctrl+Enter saves.
            </p>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={savingNote}>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={(e) => {
                  e.preventDefault();
                  void handleSaveNote();
                }}
                disabled={savingNote}
              >
                {savingNote ? "Saving…" : "Save"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </DialogContent>
    </Dialog>
  );
}
