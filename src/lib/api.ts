import { invoke } from "@tauri-apps/api/core";

export class ApiError extends Error {
  status: number;
  detail?: unknown;
  body?: unknown;

  constructor(
    message: string,
    options: { status: number; detail?: unknown; body?: unknown },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.detail = options.detail;
    this.body = options.body;
  }
}

export type ApiMod = {
  mod_id: number;
  name: string | null;
  author: string | null;
  version: string | null;
  icon: string | null;
  active_conflicting_assets: number;
  active_opposing_mods: number;
};

export type ApiAddModRequest = {
  localPath: string;
  name?: string;
  modId?: number;
  version?: string;
  sourceUrl?: string;
};

export type ApiAddModResponse = {
  ok: boolean;
  inserted: number;
  name: string;
  mod_id: number | null;
  version: string | null;
  path: string;
  contents: string[];
  ingested_paks?: number;
  ingested_assets?: number;
  ingest_warning?: string;
  source_url?: string;
  metadata_warning?: string;
  synced_mod_id?: number;
};

export type ApiUploadModResponse = {
  ok: boolean;
  path: string;
  filename: string;
  size: number;
  relative_path: string;
  downloads_root: string;
};

export type ApiConflictParticipantMod = {
  mod_id: number | null;
  mod_name: string | null;
  pak_file: string;
  icon: string | null;
  is_current: boolean;
  local_download_id?: number | null;
};

export type ApiConflictParticipant = {
  pak_name: string;
  merged_tag?: string | null;
  mods: ApiConflictParticipantMod[];
};

export type ApiConflict = {
  asset_path: string;
  category?: string | null;
  conflicting_mod_count: number;
  total_paks: number;
  winner_mod_id: number | null;
  participants: ApiConflictParticipant[];
  detected_at?: string | null;
};

export type ApiNxmDownloadProgress = {
  stage?: string;
  message?: string | null;
  bytes_downloaded?: number;
  bytes_total?: number | null;
  percent?: number | null;
  error?: string | null;
  updated_at?: number | null;
  retry_count?: number;
  permanently_failed?: boolean;
};

export type ApiNxmHandoffSummary = {
  id: string;
  created_at?: number | null;
  expires_at?: number | null;
  request?: {
    raw?: string;
    game?: string;
    mod_id?: number | null;
    file_id?: number | null;
    query?: Record<string, string>;
  } | null;
  metadata?: {
    mod_info?: Record<string, unknown> | null;
    fetched_at?: number | null;
  } | null;
  progress?: ApiNxmDownloadProgress | null;
};

export type ApiNxmHandoffList = {
  ok: boolean;
  handoffs: ApiNxmHandoffSummary[];
};

export type ApiNxmPreview = {
  ok: boolean;
  handoff: ApiNxmHandoffSummary;
  game: string;
  mod_info?: Record<string, unknown> | null;
  files?: Array<Record<string, unknown>>;
  selected_file_id?: number | null;
  selected_file?: Record<string, unknown> | null;
};

export type ApiNxmIngestOptions = {
  fileId?: number;
  desiredPaks?: string[];
  activate?: boolean;
  deactivateExisting?: boolean;
};

export type ApiNxmIngestResponse = {
  ok: boolean;
  handoff: ApiNxmHandoffSummary;
  mod_id: number;
  mod_name?: string | null;
  file_id: number;
  download_id: number;
  download: Record<string, unknown>;
  selected_file?: Record<string, unknown> | null;
  activated_paks: string[];
  activation_warning?: string | null;
  deactivated_download_ids: number[];
  deactivation_warnings?: string[];
  desired_active_paks?: string[];
  needs_refresh?: boolean;
  deactivated_existing?: boolean;
};

export type ApiSubmitNxmHandoffResponse = {
  ok: boolean;
  handoff: ApiNxmHandoffSummary;
};

export type ApiSettings = {
  backend_host: string;
  backend_port: number;
  data_dir: string | null;
  marvel_rivals_root: string | null;
  marvel_rivals_local_downloads_root: string | null;
  nexus_api_key: string;
  aes_key_hex: string;
  allow_direct_api_downloads: boolean;
  repak_bin: string | null;
  retoc_cli: string | null;
  seven_zip_bin: string | null;
  validation: ApiSettingsValidation;
};

export type ApiSettingPathValidation = {
  ok: boolean;
  message: string;
  path?: string | null;
  exists?: boolean;
  reason?: string | null;
  optional?: boolean;
};

export type ApiSettingsValidation = {
  data_dir: ApiSettingPathValidation;
  marvel_rivals_root: ApiSettingPathValidation;
  marvel_rivals_local_downloads_root: ApiSettingPathValidation;
  repak_bin: ApiSettingPathValidation;
  retoc_cli: ApiSettingPathValidation;
  seven_zip_bin: ApiSettingPathValidation;
  nexus_api_key: ApiSettingPathValidation;
};

export interface ApiUpdateSettingsRequest {
  data_dir?: string;
  marvel_rivals_root?: string | null;
  marvel_rivals_local_downloads_root?: string | null;
  nexus_api_key?: string;
  aes_key_hex?: string;
  allow_direct_api_downloads?: boolean;
  repak_bin?: string | null;
  retoc_cli?: string | null;
  seven_zip_bin?: string | null;
}

export type SettingsTask =
  | "ingest_download_assets"
  | "scan_active_mods"
  | "sync_nexus"
  | "rebuild_tags"
  | "rebuild_conflicts"
  | "bootstrap_rebuild"
  | "rebuild_character_data"
  | "delete_outdated_versions"
  | "compact_images"
  | "dedupe_images"
  | "reorganize_mods";

export type ApiSettingsTaskStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed";

export type ApiSettingsTaskResponse = {
  id: string;
  task: SettingsTask;
  status: ApiSettingsTaskStatus;
  ok: boolean | null;
  exit_code: number | null;
  error?: string | null;
  output: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  metadata?: any;
};

export type ApiBootstrapStatus = {
  db_exists: boolean;
  settings_exists: boolean;
  db_path: string | null;
  settings_path: string | null;
  downloads_count: number;
  mods_count: number;
  schema_migrations: number;
  needs_bootstrap: boolean;
};

export type ApiHealthResponse = {
  ok: boolean;
  mods?: number;
  paks?: number;
  assets?: number;
  error?: string;
};

// Marvel Rivals Character and Skin Types
export type CharacterSkin = {
  variant: string;
  name: string;
};

export type Character = {
  character_id: string;
  name: string;
  skins: CharacterSkin[];
};

export type RebuildCharacterDataResponse = {
  success: boolean;
  message: string;
  characters_count: number;
  skins_count: number;
};

// Tag Lookup Types
export type TagInfo = {
  type: "character" | "skin";
  name?: string;
  character_id?: string;
  parent?: string; // Primary parent character name for skins
  parents?: string[]; // All possible parents for disambiguation
};

export type TagLookupRequest = {
  tags: string[];
};

export type TagLookupResponse = Record<string, TagInfo>;

let cachedBaseUrl: string | null = null;

export async function getBaseUrl(): Promise<string> {
  if (cachedBaseUrl) return cachedBaseUrl;

  cachedBaseUrl = (import.meta as any).env?.VITE_API_BASE_URL || null;
  if (cachedBaseUrl) return cachedBaseUrl;

  try {
    if ((window as any).__TAURI_INTERNALS__) {
      const port = await invoke<number>("get_backend_port");
      if (port) {
        cachedBaseUrl = `http://127.0.0.1:${port}`;
        return cachedBaseUrl;
      }
    }
  } catch (e) {
    console.error("Failed to get dynamic backend port, falling back to 8000", e);
  }

  cachedBaseUrl = "http://127.0.0.1:8000";
  return cachedBaseUrl;
}

async function handleError(
  res: Response,
  method: string,
  path: string,
): Promise<never> {
  let message = `${method} ${path} failed: ${res.status}`;
  let parsedBody: unknown = undefined;
  let detail: unknown = undefined;
  try {
    const raw = await res.text();
    if (raw) {
      try {
        parsedBody = JSON.parse(raw);
        if (parsedBody && typeof parsedBody === "object") {
          const container = parsedBody as Record<string, unknown>;
          detail = container.detail ?? container.message ?? container.error;
          if (detail == null) {
            detail = parsedBody;
          }
        } else {
          detail = parsedBody;
        }
      } catch {
        parsedBody = raw;
        detail = raw;
      }
    }
  } catch {
    // ignore parsing failures and use fallback message
  }

  if (typeof detail === "string" && detail.trim().length > 0) {
    message = detail.trim();
  } else if (detail && typeof detail === "object") {
    const detailObj = detail as Record<string, unknown>;
    const maybeMessage = detailObj.message ?? detailObj.detail;
    if (typeof maybeMessage === "string" && maybeMessage.trim().length > 0) {
      message = maybeMessage.trim();
    } else {
      try {
        message = JSON.stringify(detailObj);
      } catch {
        message = `${method} ${path} failed: ${res.status}`;
      }
    }
  }

  throw new ApiError(message, {
    status: res.status,
    detail,
    body: parsedBody,
  });
}

// Debug logging helper - logs to backend
async function debugLog(message: string, data?: any, level: string = "INFO") {
  try {
    const baseUrl = await getBaseUrl();
    await fetch(`${baseUrl}/api/debug/log`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, data, level }),
    });
  } catch (e) {
    // Silently fail if debug logging doesn't work
  }
}

async function getJson<T>(path: string): Promise<T> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}${path}`, {
    headers: {
      "Cache-Control": "no-cache",
      Pragma: "no-cache",
    },
  });
  if (!res.ok) {
    await handleError(res, "GET", path);
  }
  const data = await res.json();

  // Debug logging for mod details and changelogs
  if (path.includes("/api/mods/") && !path.includes("/files")) {
    const debugData = {
      status: res.status,
      hasData: !!data,
      dataKeys: data ? Object.keys(data) : [],
      // Log specific fields for debugging
      ...(path.endsWith("/changelogs")
        ? { changelogCount: Array.isArray(data) ? data.length : 0 }
        : {
            hasMod: !!(data as any)?.mod,
            hasDescription: !!(data as any)?.mod?.description,
            descriptionPreview: (data as any)?.mod?.description?.substring(
              0,
              100,
            ),
          }),
    };
    console.log(`[API] GET ${path}`, debugData);
    // Also send to backend for production debugging
    await debugLog(`GET ${path}`, debugData);
  }

  return data;
}

async function postJson<TReq, TRes>(path: string, body: TReq): Promise<TRes> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    await handleError(res, "POST", path);
  }
  return res.json();
}

async function patchJson<TReq, TRes>(path: string, body: TReq): Promise<TRes> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    await handleError(res, "PATCH", path);
  }
  return res.json();
}

async function putJson<TReq, TRes>(path: string, body: TReq): Promise<TRes> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    await handleError(res, "PUT", path);
  }
  return res.json();
}

async function deleteJson<TRes>(path: string): Promise<TRes> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}${path}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    await handleError(res, "DELETE", path);
  }
  return res.json();
}

export async function listMods(limit = 100): Promise<ApiMod[]> {
  return getJson<ApiMod[]>(`/api/mods?limit=${limit}`);
}

export async function listConflicts(
  limit = 20,
  active = false,
): Promise<ApiConflict[]> {
  const path = active ? "/api/conflicts/active" : "/api/conflicts";
  return getJson<ApiConflict[]>(`${path}?limit=${limit}`);
}

export async function getHealth(): Promise<ApiHealthResponse> {
  return getJson<ApiHealthResponse>("/health");
}

export async function addMod(
  req: ApiAddModRequest,
): Promise<ApiAddModResponse> {
  return postJson<ApiAddModRequest, ApiAddModResponse>("/api/mods/add", req);
}

export async function uploadModFile(file: File): Promise<ApiUploadModResponse> {
  const form = new FormData();
  form.append("file", file);
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}/api/mods/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    let message: string | undefined;
    try {
      const raw = await res.text();
      if (raw) {
        try {
          const parsed = JSON.parse(raw);
          message = parsed?.detail || parsed?.message || parsed?.error;
        } catch (err) {
          message = raw;
        }
      }
    } catch (err) {
      message = undefined;
    }
    throw new Error(
      message?.trim() || `Upload failed with status ${res.status}`,
    );
  }
  return res.json();
}

export async function refreshConflicts(): Promise<{ ok: boolean }> {
  return postJson<{}, { ok: boolean }>("/api/refresh/conflicts", {});
}

export async function copyToDownloads(
  sourcePath: string,
): Promise<ApiUploadModResponse> {
  return postJson<{ source_path: string }, ApiUploadModResponse>(
    "/api/mods/copy-to-downloads",
    { source_path: sourcePath },
  );
}

export async function getSettings(): Promise<ApiSettings> {
  return getJson<ApiSettings>("/api/settings");
}

export async function updateSettings(
  payload: ApiUpdateSettingsRequest,
): Promise<ApiSettings> {
  return putJson<ApiUpdateSettingsRequest, ApiSettings>(
    "/api/settings",
    payload,
  );
}

export async function runSettingsTask(
  task: SettingsTask,
): Promise<ApiSettingsTaskResponse> {
  return postJson<{ task: SettingsTask }, ApiSettingsTaskResponse>(
    "/api/settings/run-task",
    { task },
  );
}

export async function getSettingsTaskJob(
  jobId: string,
): Promise<ApiSettingsTaskResponse> {
  return getJson<ApiSettingsTaskResponse>(`/api/settings/tasks/${jobId}`);
}

export async function listSettingsTaskJobs(): Promise<
  ApiSettingsTaskResponse[]
> {
  return getJson<ApiSettingsTaskResponse[]>("/api/settings/tasks");
}

export async function getBootstrapStatus(): Promise<ApiBootstrapStatus> {
  return getJson<ApiBootstrapStatus>("/api/bootstrap/status");
}

export async function validatePath(
  field: string,
  value: string,
): Promise<{
  ok: boolean;
  message: string;
  exists: boolean;
  reason: string | null;
}> {
  return postJson<
    { field: string; value: string },
    {
      ok: boolean;
      message: string;
      exists: boolean;
      reason: string | null;
    }
  >("/api/settings/validate-path", { field, value });
}

// NXM Protocol Management
export type NxmProtocolStatus = {
  registered: boolean;
  tauri_path?: string | null;
  registered_path?: string | null;
  system: string;
  error?: string;
};

export async function getNxmProtocolStatus(): Promise<NxmProtocolStatus> {
  return getJson<NxmProtocolStatus>("/api/nxm/protocol/status");
}

export async function registerNxmProtocol(
  tauriPath: string,
): Promise<{ ok: boolean; message?: string; error?: string }> {
  return postJson<
    { tauri_path: string },
    { ok: boolean; message?: string; error?: string }
  >("/api/nxm/protocol/register", { tauri_path: tauriPath });
}

export async function unregisterNxmProtocol(): Promise<{
  ok: boolean;
  message?: string;
  error?: string;
}> {
  return postJson<
    Record<string, never>,
    { ok: boolean; message?: string; error?: string }
  >("/api/nxm/protocol/unregister", {});
}

export type LastNxmUrl = {
  ok: boolean;
  last_url: {
    url: string;
    received_at: string;
    parsed?: {
      game_domain: string;
      mod_id: number;
      file_id: number;
      query_params: Record<string, string>;
      has_key: boolean;
      has_expires: boolean;
      has_user_id: boolean;
    };
    parse_error?: string;
  } | null;
  message?: string;
};

export async function getLastNxmUrl(): Promise<LastNxmUrl> {
  return getJson<LastNxmUrl>("/api/nxm/last-received");
}

export async function assignModId(payload: { local_paths: string[], nexus_mod_id: number, game: string }): Promise<{ ok: boolean; error?: string; renamed_count?: number }> {
  const url = await getBaseUrl();
  const res = await fetch(`${url}/api/mods/assign-mod-id`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

// Mod details
export type ApiModDetails = {
  mod?: {
    mod_id: number;
    name: string | null;
    author: string | null;
    version?: string | null;
    picture_url?: string | null;
    summary?: string | null;
    description?: string | null;
    description_bbcode?: string | null;
    mod_downloads?: number | null;
    mod_unique_downloads?: number | null;
    endorsement_count?: number | null;
    status?: string | null;
  } | null;
  latest_file?: {
    file_id?: number;
    file_name?: string;
    file_version?: string;
    file_category?: string;
    file_size_in_bytes?: number;
    is_primary?: number | boolean;
    uploaded_at?: string;
    version_key?: string | null;
  } | null;
  local_count?: number;
  active_conflicting_assets?: number;
  active_opposing_mods?: number;
  tags?: string[];
};

export async function getModDetails(modId: number): Promise<ApiModDetails> {
  return getJson<ApiModDetails>(`/api/mods/${modId}`);
}

export async function updateModDetails(
  modId: number,
  data: { description?: string },
): Promise<{ ok: boolean }> {
  try {
    return patchJson<{ description?: string }, { ok: boolean }>(
      `/api/mods/${modId}`,
      data,
    );
  } catch (e) {
    console.warn("updateModDetails failed", e);
    throw e;
  }
}

export type ApiModFile = {
  file_id: number;
  name: string;
  version: string | null;
  category: string | null;
  size_in_bytes: number | null;
  is_primary: number | boolean | null;
  uploaded_at: string | null;
};

export async function getModFiles(modId: number): Promise<ApiModFile[]> {
  return getJson<ApiModFile[]>(`/api/mods/${modId}/files`);
}

export type ApiChangelog = {
  version: string | null;
  changelog: string | null;
  uploaded_at: string | null;
};

export async function getModChangelogs(modId: number): Promise<ApiChangelog[]> {
  return getJson<ApiChangelog[]>(`/api/mods/${modId}/changelogs`);
}

// Mod Images
export type ModImage = {
  id: number;
  source: "nexus" | "custom";
  url?: string; // For nexus images
  data?: string; // For custom images (base64)
  filename?: string;
  mimeType?: string;
  uploadedAt?: string;
  /** Explicitly starred as the mod's card preview. */
  isPreview?: boolean;
};

export type ApiModImagesResponse = {
  ok: boolean;
  nexus_images: ModImage[];
  custom_images: ModImage[];
  /** True when the mod has a Nexus picture but the user removed it from the list. */
  nexus_image_hidden?: boolean;
};

export async function fetchModImages(modId: number): Promise<ModImage[]> {
  const response = await getJson<ApiModImagesResponse>(
    `/api/mods/${modId}/images`,
  );
  return [...response.nexus_images, ...response.custom_images];
}

/** Images plus whether the Nexus picture is currently hidden. */
export async function fetchModImagesDetailed(
  modId: number,
): Promise<{ images: ModImage[]; nexusHidden: boolean }> {
  const response = await getJson<ApiModImagesResponse>(
    `/api/mods/${modId}/images`,
  );
  return {
    images: [...response.nexus_images, ...response.custom_images],
    nexusHidden: Boolean(response.nexus_image_hidden),
  };
}

// ─── Activity history ────────────────────────────────────────────────────────

export type ActivityEntry = {
  id: number;
  at: string;
  kind: string;
  summary: string;
  detail: string | null;
};

/**
 * What the app did recently, newest first.
 *
 * Toasts vanish after four seconds, so "did that actually apply?" had no answer
 * short of reading backend.log. This is the same events in plain language.
 */
export async function listActivity(limit = 100): Promise<ActivityEntry[]> {
  const response = await getJson<{ ok: boolean; entries: ActivityEntry[] }>(
    `/api/activity?limit=${limit}`,
  );
  return response.entries ?? [];
}

export async function clearActivity(): Promise<{ ok: boolean; removed: number }> {
  return postJson<Record<string, never>, { ok: boolean; removed: number }>(
    `/api/activity/clear`,
    {},
  );
}

// ─── Bulk operations ─────────────────────────────────────────────────────────

/**
 * Turn several mods on or off at once.
 *
 * A single call rather than one per mod because the conflict rebuild that
 * follows each activation is the expensive part; batching it is the whole point.
 */
export async function bulkActivate(
  downloadIds: number[],
  activate: boolean,
): Promise<{ ok: boolean; changed: number; skipped: number; failed: number }> {
  return postJson<
    { download_ids: number[]; activate: boolean },
    { ok: boolean; changed: number; skipped: number; failed: number }
  >(`/api/local_downloads/bulk-activate`, {
    download_ids: downloadIds,
    activate,
  });
}

/** Add one tag to several mods. */
export async function bulkTag(
  modIds: number[],
  tag: string,
): Promise<{ ok: boolean; added: number; skipped: number; tag: string }> {
  return postJson<
    { mod_ids: number[]; tag: string },
    { ok: boolean; added: number; skipped: number; tag: string }
  >(`/api/mods/bulk-tag`, { mod_ids: modIds, tag });
}

// ─── Per-pak notes and removals ──────────────────────────────────────────────

export type ModFileNote = { note: string; updatedAt: string };

/**
 * Notes the user wrote against individual .pak files.
 *
 * Mods routinely ship a dozen variants called A_rogueVA / A_rogueVB / A_rogueVC,
 * which say nothing about what they change. Keyed by pak name so a rebuild that
 * renumbers rows cannot orphan them.
 */
export async function getFileNotes(
  downloadId: number,
): Promise<Record<string, ModFileNote>> {
  const response = await getJson<{ ok: boolean; notes: Record<string, ModFileNote> }>(
    `/api/local_downloads/${downloadId}/file-notes`,
  );
  return response.notes ?? {};
}

/** Save a note, or clear it by passing an empty string. */
export async function setFileNote(
  downloadId: number,
  pakName: string,
  note: string,
): Promise<{ ok: boolean; pak_name: string; note: string }> {
  return postJson<
    { pak_name: string; note: string },
    { ok: boolean; pak_name: string; note: string }
  >(`/api/local_downloads/${downloadId}/file-notes`, { pak_name: pakName, note });
}

export type HiddenModFile = {
  download_id: number;
  pak_name: string;
  hidden_at: string;
  mod_name: string | null;
};

/**
 * Paks the user removed from their mods.
 *
 * Removals used to live only in local_downloads.contents, which every rebuild
 * overwrites from the archive — so they all came back. They are recorded
 * separately now, and this is what lets the app offer to undo them.
 */
export async function listHiddenFiles(): Promise<HiddenModFile[]> {
  const response = await getJson<{ ok: boolean; files: HiddenModFile[] }>(
    `/api/local_downloads/hidden-files`,
  );
  return response.files ?? [];
}

/** Stop hiding removed paks. Omit ids to restore every one of them. */
export async function restoreHiddenFiles(
  downloadIds?: number[],
): Promise<{ ok: boolean; restored: number }> {
  return postJson<{ download_ids?: number[] }, { ok: boolean; restored: number }>(
    `/api/local_downloads/hidden-files/restore`,
    downloadIds && downloadIds.length > 0 ? { download_ids: downloadIds } : {},
  );
}

/**
 * Delete a pak from the mod's archive for good.
 *
 * The destructive counterpart to removeDownloadFile, which only hides. The
 * archive is rewritten on disk, so a rebuild cannot bring the file back.
 */
export async function deleteDownloadFile(
  downloadId: number,
  pakName: string,
): Promise<{ ok: boolean; deleted: string; members_removed: number }> {
  return postJson<
    { pak_name: string },
    { ok: boolean; deleted: string; members_removed: number }
  >(`/api/local_downloads/${downloadId}/delete-file`, { pak_name: pakName });
}

/**
 * Put one removed pak back into a mod.
 *
 * Takes effect immediately: the file was never deleted, and hiding is applied
 * when the mod is read, so nothing has to be rebuilt.
 */
export async function restoreDownloadFile(
  downloadId: number,
  pakName: string,
): Promise<{ ok: boolean; restored: number; pak_name: string }> {
  return postJson<
    { pak_name: string },
    { ok: boolean; restored: number; pak_name: string }
  >(`/api/local_downloads/${downloadId}/restore-file`, { pak_name: pakName });
}

/** One image found inside a mod's own archive. */
export type ArchiveImage = {
  /** Path inside the archive — the handle used to import it. */
  entry: string;
  name: string;
  width: number;
  height: number;
  bytes: number;
  /** Small JPEG data URL, for the picker only. */
  thumbnail: string;
};

/**
 * Images shipped inside the mod's own archive.
 *
 * Nexus publishes one picture per mod and its API exposes no gallery, so this
 * is where the other variants actually live — and it works for hand-made .pak
 * drops that were never on Nexus at all. Nothing is stored by this call.
 */
export async function listArchiveImages(
  downloadId: number,
): Promise<{ images: ArchiveImage[]; reason?: string }> {
  const response = await getJson<{
    ok: boolean;
    images: ArchiveImage[];
    reason?: string;
  }>(`/api/local_downloads/${downloadId}/archive-images`);
  return { images: response.images ?? [], reason: response.reason };
}

/** A cover image of some Nexus mod matching a character or skin name. */
export type NexusImageResult = {
  url: string;
  thumbnail: string;
  modName: string;
  modId: number;
  author: string;
  adult: boolean;
  /** Which search phrase found it — the full one means an exact skin match. */
  matchedTerm: string;
  /** True when the image belongs to this very mod, not a similar one. */
  ownMod?: boolean;
};

/**
 * Cover pictures of Nexus mods matching a name.
 *
 * For a mod that ships no artwork of its own. This is not that mod's gallery —
 * the mod page is behind a Cloudflare JavaScript challenge that 403s automated
 * requests — but other mods for the same character are reachable through the
 * search API, which is the same path Browse Nexus already uses.
 */
export async function searchNexusImages(
  query: string,
  count = 24,
  modId?: number | null,
): Promise<NexusImageResult[]> {
  // Passing the mod id puts that mod's own pictures at the front — the cover
  // plus any gallery links its author wrote into the description. That is
  // everything Nexus will give up for a specific mod.
  const linked = modId != null && modId > 0 ? `&mod_id=${modId}` : "";
  const response = await getJson<{ ok: boolean; images: NexusImageResult[] }>(
    `/api/nexus/image-search?query=${encodeURIComponent(query)}&count=${count}${linked}`,
  );
  return response.images ?? [];
}

/** A Nexus mod this download might be, offered when assigning a mod id. */
export type ModIdSuggestion = {
  modId: number;
  name: string;
  author: string;
  thumbnail: string | null;
  modPageUrl: string;
  adult: boolean;
  matchedTerm: string;
};

/**
 * Nexus mods a download is plausibly a copy of.
 *
 * Assigning an id meant reading it off the website and typing it in. The
 * download's own file name and tags are enough to offer candidates — but they
 * stay suggestions, because a wrong id silently attaches the wrong artwork.
 */
export async function suggestModIds(
  downloadId: number,
  count = 8,
): Promise<{ suggestions: ModIdSuggestion[]; currentModId: number | null; searchedFor: string[] }> {
  const response = await getJson<{
    ok: boolean;
    suggestions: ModIdSuggestion[];
    currentModId: number | null;
    searchedFor: string[];
  }>(`/api/local_downloads/${downloadId}/mod-id-suggestions?count=${count}`);
  return {
    suggestions: response.suggestions ?? [],
    currentModId: response.currentModId ?? null,
    searchedFor: response.searchedFor ?? [],
  };
}

/** Store the chosen archive images against the mod. Duplicates are skipped. */
export async function importArchiveImages(
  downloadId: number,
  entries: string[],
): Promise<{
  ok: boolean;
  mod_id: number;
  imported: number;
  duplicates: number;
  failed: number;
}> {
  return postJson<
    { entries: string[] },
    { ok: boolean; mod_id: number; imported: number; duplicates: number; failed: number }
  >(`/api/local_downloads/${downloadId}/archive-images/import`, { entries });
}

/**
 * Remove the Nexus picture from a mod's gallery, or put it back.
 *
 * Nothing is deleted upstream — the app just stops offering it, so this is
 * reversible and safe to hand to a delete button.
 */
export async function setNexusImageHidden(
  modId: number,
  hidden: boolean,
): Promise<{ ok: boolean; hidden: boolean }> {
  return postJson<Record<string, never>, { ok: boolean; hidden: boolean }>(
    `/api/mods/${modId}/images/nexus/${hidden ? "hide" : "show"}`,
    {},
  );
}

export async function uploadModImages(
  modId: number,
  files: File[],
): Promise<{ ok: boolean; uploaded_count: number; image_ids: number[] }> {
  // Convert files to base64
  const images = await Promise.all(
    files.map(async (file) => {
      const base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const result = reader.result as string;
          // Extract base64 data (remove data:image/...;base64, prefix)
          const base64Data = result.split(",")[1] || result;
          resolve(base64Data);
        };
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });

      return {
        data: base64,
        filename: file.name,
        mimeType: file.type,
      };
    }),
  );

  return postJson<
    { images: Array<{ data: string; filename: string; mimeType: string }> },
    { ok: boolean; uploaded_count: number; image_ids: number[] }
  >(`/api/mods/${modId}/images`, { images });
}

export async function uploadModImagesByPath(
  modId: number,
  paths: string[],
): Promise<{ ok: boolean; uploaded_count: number; image_ids: number[] }> {
  return postJson<{ paths: string[] }, { ok: boolean; uploaded_count: number; image_ids: number[] }>(
    `/api/mods/${modId}/images/upload-by-path`,
    { paths },
  );
}

export async function uploadModImagesBase64(
  modId: number,
  images: { data: string; filename?: string; mimeType?: string }[],
): Promise<{ ok: boolean; uploaded_count: number; image_ids: number[] }> {
  return postJson<{ images: any[] }, { ok: boolean; uploaded_count: number; image_ids: number[] }>(
    `/api/mods/${modId}/images`,
    { images }
  );
}

/**
 * Persist a user-chosen image order. The first id becomes the card preview.
 *
 * Ordering was upload order with no way to change it, and the preview endpoint
 * selected the lowest row id, so a better screenshot added later could never be
 * promoted.
 */
export async function reorderModImages(
  modId: number,
  imageIds: number[],
): Promise<{ ok: boolean; order: number[] }> {
  return postJson<{ image_ids: number[] }, { ok: boolean; order: number[] }>(
    `/api/mods/${modId}/images/reorder`,
    { image_ids: imageIds },
  );
}

export async function deleteModImage(
  imageId: number,
): Promise<{ ok: boolean; deleted_id: number }> {
  return deleteJson<{ ok: boolean; deleted_id: number }>(
    `/api/mods/images/${imageId}`,
  );
}

export type ModCustomPreviews = {
  /** modId -> data URL of the image to show on the card. */
  images: Record<number, string>;
  /**
   * Mods where the user explicitly starred an image.
   *
   * The card used to prefer the Nexus picture_url unconditionally, so a chosen
   * image never showed for a mod linked with Assign Mod ID. Only an explicit
   * choice may outrank the Nexus artwork — "first custom image" is a default,
   * not a decision.
   */
  explicit: Set<number>;
};

export async function getModCustomImagePreviews(
  modIds: number[],
): Promise<ModCustomPreviews> {
  if (!modIds || modIds.length === 0) {
    return { images: {}, explicit: new Set() };
  }
  const idsParam = modIds.join(",");
  const response = await getJson<{
    ok: boolean;
    images: Record<string, string>;
    explicit?: string[];
  }>(`/api/mods/custom-images-preview?mod_ids=${encodeURIComponent(idsParam)}`);
  // Convert string keys to number keys
  const images: Record<number, string> = {};
  for (const [key, value] of Object.entries(response.images)) {
    images[Number(key)] = value;
  }
  return {
    images,
    explicit: new Set((response.explicit ?? []).map(Number)),
  };
}

/**
 * Remove one pak from a mod without deleting the whole mod.
 *
 * The source archive is untouched — re-running "Rebuild Local Downloads"
 * restores the file.
 */
export async function removeDownloadFile(
  downloadId: number,
  pakName: string,
): Promise<{ ok: boolean; removed: string; remaining: number }> {
  return postJson<
    { pak_name: string },
    { ok: boolean; removed: string; remaining: number }
  >(`/api/local_downloads/${downloadId}/remove-file`, { pak_name: pakName });
}

/** Mark an image as the mod's card preview. */
export async function setModImagePreview(
  modId: number,
  imageId: number,
): Promise<{ ok: boolean }> {
  return postJson<Record<string, never>, { ok: boolean }>(
    `/api/mods/${modId}/images/${imageId}/preview`,
    {},
  );
}

// Downloads
export type ApiDownload = {
  id: number;
  name: string;
  mod_id: number | null;
  version: string | null;
  path: string;
  contents: string[];
  /** Files removed from this mod, kept out of `contents` until restored. */
  hidden_contents?: string[];
  active_paks: string[];
  // Client-side aggregation helper: when grouping multiple local_downloads for the same mod,
  // keep track of which download rows were merged.
  source_download_ids?: number[];
  // Client-side aggregation helper: track all latest_file_ids across merged downloads
  source_file_ids?: number[];
  // Client-side aggregation helper: track all source paths across merged downloads
  source_paths?: string[];
  created_at: string;
  mod_name: string | null;
  mod_author: string | null;
  picture_url: string | null;
  tags: string[];
  custom_tag_names?: string[];
  mod_downloads?: number | null;
  endorsement_count?: number | null;
  mod_author_profile_url?: string | null;
  mod_author_member_id?: number | null;
  mod_author_avatar_url?: string | null;
  mod_created_time?: string | null;
  mod_updated_at?: string | null;
  download_id?: number;
  latest_version?: string | null;
  latest_uploaded_at?: string | null;
  latest_file_id?: number | null;
  latest_version_key?: string | null;
  latest_file_name?: string | null;
  local_version_key?: string | null;
  needs_update?: boolean;
  contains_adult_content?: boolean;
  needs_manual_mod_id?: boolean;
  rename_status?: string | null;
  rename_error?: string | null;
};

export interface ApiPakVersionStatus {
  pak_name: string;
  mod_id: number | null;
  source_zip: string | null;
  local_download_id: number | null;
  local_path: string | null;
  local_name: string | null;
  local_version: string | null;
  reference_file_id: number | null;
  reference_version: string | null;
  version_status:
    | "match"
    | "mismatch"
    | "missing_local_version"
    | "missing_remote_version";
  needs_update: boolean;
  display_version?: string | null;
}

export interface ApiPakAsset {
  pak_name: string;
  assets: string[];
}

export async function listDownloads(): Promise<ApiDownload[]> {
  return getJson<ApiDownload[]>(`/api/downloads`);
}

export type ApiDownloadsSummary = {
  ok: boolean;
  total_size_bytes: number;
  total_size_human: string;
  download_count: number;
  missing_paths: string[];
  last_check?: string | null;
};

export async function getDownloadsSummary(): Promise<ApiDownloadsSummary> {
  return getJson<ApiDownloadsSummary>(`/api/downloads/summary`);
}

export async function setActivePaks(downloadId: number, active_paks: string[]) {
  return postJson<{ active_paks: string[] }, { ok: boolean }>(
    `/api/local_downloads/${downloadId}/set-active`,
    { active_paks },
  );
}

export async function disableAllMods(): Promise<{ ok: boolean }> {
  return postJson<{}, { ok: boolean }>(`/api/mods/disable-all`, {});
}

export async function scanActive(): Promise<{ ok: boolean }> {
  return postJson<{}, { ok: boolean }>(`/api/scan/active`, {});
}

export async function getLocalDownload(
  downloadId: number,
): Promise<ApiDownload> {
  return getJson<ApiDownload>(`/api/local_downloads/${downloadId}`);
}

export async function getPakVersionStatus(
  params: {
    modId?: number | null;
    downloadIds?: number[];
    onlyNeedsUpdate?: boolean;
  } = {},
): Promise<ApiPakVersionStatus[]> {
  const search = new URLSearchParams();
  if (params.modId != null) {
    search.set("mod_id", String(params.modId));
  }
  if (params.downloadIds && params.downloadIds.length > 0) {
    search.set("download_ids", params.downloadIds.join(","));
  }
  if (params.onlyNeedsUpdate) {
    search.set("only_needs_update", "true");
  }
  const query = search.toString();
  const path = query
    ? `/api/pak-version-status?${query}`
    : `/api/pak-version-status`;
  return getJson<ApiPakVersionStatus[]>(path);
}

// By-name activation/deactivation (server-side convenience endpoints)
export async function activateByName(
  name: string,
): Promise<{ ok: boolean } & { copied?: string[] }> {
  return postJson<{ name: string }, { ok: boolean; copied?: string[] }>(
    `/api/local_downloads/activate-by-name`,
    { name },
  );
}

export async function deactivateByName(
  name: string,
): Promise<{ ok: boolean } & { removed?: string[] }> {
  return postJson<{ name: string }, { ok: boolean; removed?: string[] }>(
    `/api/local_downloads/deactivate-by-name`,
    { name },
  );
}

export async function getPakAssets(
  downloadIds: number[],
): Promise<ApiPakAsset[]> {
  if (!downloadIds || downloadIds.length === 0) {
    return [];
  }
  const search = new URLSearchParams();
  search.set("download_ids", downloadIds.join(","));
  return getJson<ApiPakAsset[]>(`/api/pak-assets?${search.toString()}`);
}

export type ApiCheckModUpdateResponse = {
  ok: boolean;
  mod_id: number;
  needs_update: boolean;
  pending: Array<{
    pak_name?: string | null;
    local_download_id?: number | null;
    local_version?: string | null;
    reference_version?: string | null;
    version_status?: string | null;
    display_version?: string | null;
  }>;
  metadata_warning?: string;
  synced_mod_id?: number | null;
  checked_download_ids?: number[];
};

export type ApiUpdateModResponse = {
  ok: boolean;
  mod_id: number;
  mod_name?: string | null;
  latest_version: string;
  latest_file_id: number;
  latest_uploaded_at?: string | null;
  download_id: number;
  download: Record<string, unknown>;
  activated_paks: string[];
  activation_warning?: string | null;
  deactivated_download_ids: number[];
  deactivation_warnings?: string[];
  preflight_metadata?: Record<string, unknown>;
  local_versions: Array<Record<string, unknown>>;
  already_latest?: boolean;
  needs_refresh?: boolean;
};

export async function updateMod(
  modId: number,
  options: {
    fileId?: number;
    activate?: boolean;
    desiredPaks?: string[];
    force?: boolean;
    handoffId?: string;
  } = {},
): Promise<ApiUpdateModResponse> {
  const payload: Record<string, unknown> = {};
  if (typeof options.fileId === "number") payload.file_id = options.fileId;
  if (typeof options.activate === "boolean")
    payload.activate = options.activate;
  if (Array.isArray(options.desiredPaks))
    payload.desired_paks = options.desiredPaks;
  if (options.force) payload.force = true;
  if (typeof options.handoffId === "string" && options.handoffId.trim()) {
    payload.handoff_id = options.handoffId.trim();
  }
  return postJson<Record<string, unknown>, ApiUpdateModResponse>(
    `/api/mods/${modId}/update`,
    payload,
  );
}

export async function checkModUpdate(
  modId: number,
): Promise<ApiCheckModUpdateResponse> {
  return postJson<Record<string, never>, ApiCheckModUpdateResponse>(
    `/api/mods/${modId}/check-update`,
    {},
  );
}

export type DeleteLocalDownloadsResponse = {
  ok: boolean;
  deleted: number;
  removed_mod_ids: number[];
  removed_files?: string[];
  missing_files?: string[];
  failed_files?: string[];
};

export async function deleteLocalDownloads(
  downloadIds: number[],
  modId?: number | null,
): Promise<DeleteLocalDownloadsResponse> {
  const payload: Record<string, unknown> = {};
  if (Array.isArray(downloadIds) && downloadIds.length > 0) {
    payload.download_ids = downloadIds;
  }
  if (modId != null) {
    payload.mod_id = modId;
  }
  if (Object.keys(payload).length === 0) {
    throw new Error("At least one download id or mod id is required");
  }
  return postJson<Record<string, unknown>, DeleteLocalDownloadsResponse>(
    `/api/local_downloads/delete`,
    payload,
  );
}

export async function listNxmHandoffs(): Promise<ApiNxmHandoffSummary[]> {
  const response = await getJson<ApiNxmHandoffList>(`/api/nxm/handoffs`);
  return Array.isArray(response?.handoffs) ? response.handoffs : [];
}

export async function getNxmHandoff(
  handoffId: string,
): Promise<{ ok: boolean; handoff: ApiNxmHandoffSummary }> {
  const encoded = encodeURIComponent(handoffId);
  return getJson<{ ok: boolean; handoff: ApiNxmHandoffSummary }>(
    `/api/nxm/handoff/${encoded}`,
  );
}

export async function previewNxmHandoff(
  handoffId: string,
): Promise<ApiNxmPreview> {
  const encoded = encodeURIComponent(handoffId);
  return getJson<ApiNxmPreview>(`/api/nxm/handoff/${encoded}/preview`);
}

export async function ingestNxmHandoff(
  handoffId: string,
  options: ApiNxmIngestOptions = {},
): Promise<ApiNxmIngestResponse> {
  const payload: Record<string, unknown> = {};
  if (typeof options.fileId === "number") {
    payload.file_id = options.fileId;
  }
  if (Array.isArray(options.desiredPaks)) {
    payload.desired_paks = options.desiredPaks;
  }
  if (typeof options.activate === "boolean") {
    payload.activate = options.activate;
  }
  if (typeof options.deactivateExisting === "boolean") {
    payload.deactivate_existing = options.deactivateExisting;
  }
  const encoded = encodeURIComponent(handoffId);
  return postJson<Record<string, unknown>, ApiNxmIngestResponse>(
    `/api/nxm/handoff/${encoded}/ingest`,
    payload,
  );
}

// Character and Skin Data API
export async function getCharacters(): Promise<Character[]> {
  return getJson<Character[]>("/api/characters");
}

export async function getCharacterSkins(
  characterId: string,
): Promise<CharacterSkin[]> {
  return getJson<CharacterSkin[]>(`/api/characters/${characterId}/skins`);
}

export async function rebuildCharacterData(): Promise<RebuildCharacterDataResponse> {
  return postJson<{}, RebuildCharacterDataResponse>(
    "/api/rebuild-character-data",
    {},
  );
}

export async function lookupTags(tags: string[]): Promise<TagLookupResponse> {
  return postJson<TagLookupRequest, TagLookupResponse>(
    "/api/characters/lookup-tags",
    { tags },
  );
}

export async function dismissNxmHandoff(
  handoffId: string,
): Promise<ApiNxmHandoffSummary> {
  const encoded = encodeURIComponent(handoffId);
  const response = await deleteJson<{
    ok: boolean;
    handoff: ApiNxmHandoffSummary;
  }>(`/api/nxm/handoff/${encoded}`);
  return response.handoff;
}

/**
 * Signal the backend to cancel an in-progress NXM download.
 *
 * The backend sets a per-handoff cancellation flag that is polled every
 * 1 MiB chunk inside the download loop. When detected the partial file is
 * deleted and the handoff record is removed, so the download never appears
 * in the mod list.
 *
 * This call returns as soon as the flag is set; the actual abort happens
 * on the next chunk boundary (at most ~1 MiB of extra data is downloaded).
 */
export async function cancelNxmHandoff(
  handoffId: string,
): Promise<{ ok: boolean; cancelled: boolean; handoff_id: string }> {
  const encoded = encodeURIComponent(handoffId);
  return postJson<Record<string, never>, { ok: boolean; cancelled: boolean; handoff_id: string }>(
    `/api/nxm/handoff/${encoded}/cancel`,
    {},
  );
}

export async function submitNxmHandoff(
  nxmUri: string,
): Promise<ApiSubmitNxmHandoffResponse> {
  return postJson<{ nxm: string }, ApiSubmitNxmHandoffResponse>(
    `/api/nxm/handoff`,
    { nxm: nxmUri },
  );
}

// Favourites
export async function toggleFavourite(
  modId: number,
): Promise<{ ok: boolean; favourited: boolean }> {
  return postJson<{ mod_id: number }, { ok: boolean; favourited: boolean }>(
    "/api/favourites/toggle",
    { mod_id: modId },
  );
}

export async function fetchFavourites(): Promise<number[]> {
  const response = await getJson<{ ok: boolean; mod_ids: number[] }>(
    "/api/favourites",
  );
  return response.mod_ids;
}

// Game Version Check
export type GameVersionCheckResponse = {
  ok: boolean;
  latest_modified: string | null;
  file_count: number;
  latest_file: string | null;
  error?: string;
};

export async function getGameVersionCheck(): Promise<GameVersionCheckResponse> {
  return getJson<GameVersionCheckResponse>("/api/game-version/check");
}

// ─── Collections API ──────────────────────────────────────────────────────────

export type ApiCollectionModFile = {
  id: number;
  entry_id: string;
  file_id: number;
  mod_id: number | null;
  optional: number; // 0 = required, 1 = optional
  version: string;
  file_name: string;
  file_uri: string;
  size_in_bytes: number | null;
  mod_name: string;
  picture_url: string;
  download_state: "pending" | "downloading" | "downloaded" | "failed";
};

export type ApiCollectionSummary = {
  id: number;
  slug: string;
  nexus_id: number | null;
  revision_num: number | null;
  game: string;
  name: string | null;
  summary: string | null;
  picture_url: string | null;
  author: string | null;
  total_mods: number | null;
  total_size: number | null;
  status: string | null;
  updated_at: string | null;
  fetched_at: string;
};

export type ApiCollection = ApiCollectionSummary & {
  revision_id: number | null;
  created_at: string | null;
  mod_files: ApiCollectionModFile[];
};

export async function listCollections(): Promise<ApiCollectionSummary[]> {
  const r = await getJson<{ ok: boolean; collections: ApiCollectionSummary[] }>("/api/collections");
  return r.collections ?? [];
}

/**
 * Every collection WITH its mod_files, in ONE request.
 *
 * Replaces listCollections() followed by getCollection() per collection — with 20
 * collections that was 21 requests to render one page, repeated on every poll.
 * The backend answers it in a fixed two SQL queries regardless of how many
 * collections exist.
 */
export async function listCollectionsDetailed(): Promise<ApiCollection[]> {
  const r = await getJson<{ ok: boolean; collections: ApiCollection[] }>(
    "/api/collections/detailed",
  );
  return r.collections ?? [];
}

export async function getCollection(id: number): Promise<ApiCollection> {
  const r = await getJson<{ ok: boolean; collection: ApiCollection }>(`/api/collections/${id}`);
  return r.collection;
}

export async function importCollection(payload: {
  nxm_url?: string;
  slug?: string;
  revision?: number;
}): Promise<ApiCollection> {
  const r = await postJson<typeof payload, { ok: boolean; collection: ApiCollection }>(
    "/api/collections/import",
    payload,
  );
  return r.collection;
}

export async function importCollectionRaw(payload: {
  slug: string;
  revision: Record<string, unknown>;
}): Promise<ApiCollection> {
  const r = await postJson<typeof payload, { ok: boolean; collection: ApiCollection }>(
    "/api/collections/import-raw",
    payload,
  );
  return r.collection;
}

export async function deleteCollection(id: number): Promise<{ ok: boolean }> {
  return deleteJson<{ ok: boolean }>(`/api/collections/${id}`);
}

export async function refreshCollection(id: number): Promise<ApiCollection> {
  const r = await postJson<Record<string, never>, { ok: boolean; collection: ApiCollection }>(
    `/api/collections/${id}/refresh`,
    {},
  );
  return r.collection;
}

export async function updateCollectionModFileState(
  collectionId: number,
  fileId: number,
  state: "pending" | "downloading" | "downloaded" | "failed",
): Promise<{ ok: boolean }> {
  return postJson<{ state: string }, { ok: boolean }>(
    `/api/collections/${collectionId}/mod-files/${fileId}/state`,
    { state },
  );
}

// ---------------------------------------------------------------------------
// Custom tag API helpers
// ---------------------------------------------------------------------------

export type CustomTag = {
  id: number;
  tag: string;
  added_at?: string | null;
};

/** Fetch all custom tags for a specific mod. */
export async function getModCustomTags(modId: number): Promise<CustomTag[]> {
  return getJson<CustomTag[]>(`/api/mods/${modId}/custom-tags`);
}

/** Add a custom tag to a mod. Returns the created (or existing) tag row. */
export async function addModCustomTag(
  modId: number,
  tag: string,
): Promise<CustomTag> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}/api/mods/${modId}/custom-tags`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tag }),
  });
  if (!res.ok) {
    await handleError(res, "POST", `/api/mods/${modId}/custom-tags`);
  }
  return res.json();
}

/** Remove a custom tag from a mod by its row ID. */
export async function removeModCustomTag(
  modId: number,
  tagId: number,
): Promise<{ ok: boolean; deleted_id: number }> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(
    `${baseUrl}/api/mods/${modId}/custom-tags/${tagId}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    await handleError(
      res,
      "DELETE",
      `/api/mods/${modId}/custom-tags/${tagId}`,
    );
  }
  return res.json();
}

/** Return all distinct custom tags across all mods (for the suggestion dropdown). */
export async function getAllCustomTags(): Promise<string[]> {
  return getJson<string[]>(`/api/mods/all-custom-tags`);
}

// ── Nexus browsing ──────────────────────────────────────────────────────────
// Backed by Nexus GraphQL v2. The v1 REST API used elsewhere in this file has
// no search endpoint at all, which is why browsing previously meant leaving the
// app for the website.

export type NexusBrowseMod = {
  modId: number;
  name: string;
  summary: string;
  version: string;
  author: string;
  uploaderProfileUrl: string | null;
  adult: boolean;
  downloads: number;
  endorsements: number;
  createdAt: string | null;
  updatedAt: string | null;
  pictureUrl: string | null;
  thumbnailUrl: string | null;
  category: string;
  modPageUrl: string | null;
  isInstalled: boolean;
};

export type NexusBrowseResult = {
  ok: boolean;
  mods: NexusBrowseMod[];
  total: number;
  offset: number;
  count: number;
  has_more: boolean;
};

export type NexusSortField =
  | "endorsements"
  | "downloads"
  | "createdAt"
  | "updatedAt"
  | "name";

/** Category names offered in the browse filter. */
export async function listNexusCategories(): Promise<string[]> {
  const data = await getJson<{ ok: boolean; categories: string[] }>(
    "/api/nexus/categories",
  );
  return data.categories ?? [];
}

export async function browseNexus(options: {
  query?: string;
  category?: string;
  author?: string;
  sortBy?: NexusSortField;
  descending?: boolean;
  includeAdult?: boolean;
  offset?: number;
  count?: number;
} = {}): Promise<NexusBrowseResult> {
  const params = new URLSearchParams();
  if (options.query) params.set("query", options.query);
  if (options.category) params.set("category", options.category);
  if (options.author) params.set("author", options.author);
  if (options.sortBy) params.set("sort_by", options.sortBy);
  if (options.descending !== undefined) params.set("descending", String(options.descending));
  if (options.includeAdult !== undefined) {
    params.set("include_adult", String(options.includeAdult));
  }
  if (options.offset !== undefined) params.set("offset", String(options.offset));
  if (options.count !== undefined) params.set("count", String(options.count));

  return getJson<NexusBrowseResult>(`/api/nexus/browse?${params.toString()}`);
}

/**
 * Store images from URLs the user pasted.
 *
 * Neither Nexus API exposes a mod's gallery — the Mod type carries one picture
 * in several sizes, and the media query cannot be narrowed to a mod — so this
 * is the user-driven way to attach the rest of a mod's screenshots.
 */
export async function uploadModImagesByUrl(
  modId: number,
  urls: string[],
): Promise<{
  ok: boolean;
  uploaded_count: number;
  image_ids: number[];
  failures: { url: string; error: string }[];
}> {
  return postJson<
    { urls: string[] },
    { ok: boolean; uploaded_count: number; image_ids: number[]; failures: { url: string; error: string }[] }
  >(`/api/mods/${modId}/images/by-url`, { urls });
}

// ── Hidden (suppressed) auto-detected tags ──────────────────────────────────
// Custom tags are rows the user created, so removing one is a DELETE. Tags
// derived from Nexus metadata or pak extraction have no row to delete, and
// removing them at the source does not stick: extraction recomputes them and the
// next sync overwrites them. Hiding records a suppression the read paths honour.

/** Auto-detected tags the user has suppressed for this mod. */
export async function getModHiddenTags(modId: number): Promise<string[]> {
  return getJson<string[]>(`/api/mods/${modId}/hidden-tags`);
}

/** Suppress an auto-detected tag. Idempotent. */
export async function hideModTag(
  modId: number,
  tag: string,
): Promise<{ ok: boolean; tag: string }> {
  return postJson<{ tag: string }, { ok: boolean; tag: string }>(
    `/api/mods/${modId}/hidden-tags`,
    { tag },
  );
}

/** Bring a suppressed tag back. */
export async function unhideModTag(
  modId: number,
  tag: string,
): Promise<{ ok: boolean; restored: string }> {
  const baseUrl = await getBaseUrl();
  const path = `/api/mods/${modId}/hidden-tags/${encodeURIComponent(tag)}`;
  const res = await fetch(`${baseUrl}${path}`, { method: "DELETE" });
  if (!res.ok) await handleError(res, "DELETE", path);
  return res.json();
}

// ── Custom Author Metadata ──────────────────────────────────────────────────

export interface CustomAuthor {
  id: number;
  display_name: string;
  author_type: "nexus" | "custom";
  nexus_member_id?: number | null;
  avatar_base64?: string | null;
}

export async function searchAuthors(query: string): Promise<CustomAuthor[]> {
  const q = encodeURIComponent(query);
  return getJson<CustomAuthor[]>(`/api/authors/search?q=${q}`);
}

export async function createOrUpdateAuthor(
  data: Omit<CustomAuthor, "id"> & { id?: number },
): Promise<CustomAuthor> {
  const baseUrl = await getBaseUrl();
  if (data.id != null) {
    // Update existing (PUT)
    const res = await fetch(`${baseUrl}/api/authors/${data.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: data.display_name,
        avatar_base64: data.avatar_base64,
        clear_avatar: data.avatar_base64 === null,
      }),
    });
    if (!res.ok) await handleError(res, "PUT", `/api/authors/${data.id}`);
    return res.json();
  } else {
    // Create new (POST)
    return postJson<any, CustomAuthor>(`/api/authors`, {
      display_name: data.display_name,
      author_type: data.author_type,
      nexus_member_id: data.nexus_member_id,
      avatar_base64: data.avatar_base64,
    });
  }
}

export async function assignModAuthor(
  modKey: string,
  authorId: number,
): Promise<void> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}/api/mods/${encodeURIComponent(modKey)}/author`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ author_id: authorId }),
  });
  if (!res.ok) await handleError(res, "PUT", `/api/mods/${encodeURIComponent(modKey)}/author`);
}

export async function clearModAuthor(modKey: string): Promise<void> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(
    `${baseUrl}/api/mods/${encodeURIComponent(modKey)}/author`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    await handleError(
      res,
      "DELETE",
      `/api/mods/${encodeURIComponent(modKey)}/author`,
    );
  }
}

// ─── Backup / restore ────────────────────────────────────────────────────────
// Backup used to be entirely client-side: a JSON projection of mod metadata with
// the index kept in localStorage. mods.db and settings.json were never captured,
// and clearing webview storage orphaned every archive. These endpoints make the
// backend (and the filesystem) authoritative.

export type ApiBackupInfo = {
  name: string;
  path: string;
  created_at: string | null;
  size_bytes: number;
  manifest_version: number | null;
  total_mods: number | null;
  active_mods: number | null;
  /** Why the archive exists: "manual", "pre-restore" or "pre-compact". */
  kind: string;
  /** Human-readable explanation shown in the backup list. */
  description: string;
  data_dir: string | null;
  marvel_rivals_root: string | null;
  downloads_root: string | null;
};

export type ApiBackupCreateResult = ApiBackupInfo & {
  ok: boolean;
  archive_name: string;
  /** Paths of older archives rotated out to keep the folder bounded. */
  pruned: string[];
};

export type ApiBackupRestoreResult = {
  ok: boolean;
  restored_from: string;
  manifest_version: number | null;
  created_at: string | null;
  remapped_paths: number;
  restored_settings: boolean;
  safety_snapshot: string | null;
  /**
   * How many mods the backend physically switched back on in ~mods.
   *
   * Restoring the database alone changes nothing a player can see: a mod is
   * active because its .pak sits in the game folder, not because a column says
   * so. `failed` counts mods the archive had active that are no longer on disk.
   */
  reactivated?: {
    activated: number;
    deactivated: number;
    failed: number;
  };
};

export async function createBackup(name?: string): Promise<ApiBackupCreateResult> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}/api/backup/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(name ? { name } : {}),
  });
  if (!res.ok) await handleError(res, "POST", "/api/backup/create");
  return (await res.json()) as ApiBackupCreateResult;
}

export async function listServerBackups(): Promise<ApiBackupInfo[]> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}/api/backup/list`);
  if (!res.ok) await handleError(res, "GET", "/api/backup/list");
  const data = (await res.json()) as { ok: boolean; backups: ApiBackupInfo[] };
  return data.backups ?? [];
}

/** Delete one archive. The backend refuses paths outside the backups folder. */
export async function deleteBackup(
  path: string,
): Promise<{ ok: boolean; deleted: string; size_bytes: number }> {
  return postJson<{ path: string }, { ok: boolean; deleted: string; size_bytes: number }>(
    "/api/backup/delete",
    { path },
  );
}

/** Delete all but the newest `keep` archives. */
export async function pruneBackups(
  keep: number,
): Promise<{ ok: boolean; removed: string[]; count: number }> {
  return postJson<{ keep: number }, { ok: boolean; removed: string[]; count: number }>(
    "/api/backup/prune",
    { keep },
  );
}

export async function restoreBackup(
  path: string,
  options: { remapPaths?: boolean } = {},
): Promise<ApiBackupRestoreResult> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}/api/backup/restore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      path,
      remap_paths: options.remapPaths !== false,
    }),
  });
  if (!res.ok) await handleError(res, "POST", "/api/backup/restore");
  return (await res.json()) as ApiBackupRestoreResult;
}

// ─── Collection bulk operations ──────────────────────────────────────────────
// Enabling a collection previously meant one PATCH per member file, each
// triggering its own conflict rebuild.

export type ApiCollectionBulkResult = {
  ok: boolean;
  collection_id: number;
  activated?: number;
  deactivated?: number;
  applied: Array<{ file_id: number; mod_id: number | null; local_download_id: number }>;
  skipped: Array<{ file_id: number; mod_id: number | null; reason: string }>;
  total_members: number;
};

export async function activateCollection(
  collectionId: number,
): Promise<ApiCollectionBulkResult> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}/api/collections/${collectionId}/activate`, {
    method: "POST",
  });
  if (!res.ok) await handleError(res, "POST", `/api/collections/${collectionId}/activate`);
  return (await res.json()) as ApiCollectionBulkResult;
}

export async function deactivateCollection(
  collectionId: number,
): Promise<ApiCollectionBulkResult> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(`${baseUrl}/api/collections/${collectionId}/deactivate`, {
    method: "POST",
  });
  if (!res.ok) {
    await handleError(res, "POST", `/api/collections/${collectionId}/deactivate`);
  }
  return (await res.json()) as ApiCollectionBulkResult;
}

export type ApiCollectionUpdateCheck = {
  ok: boolean;
  collection_id: number;
  needs_update: boolean;
  pending: Array<{
    pak_name: string | null;
    mod_id: number | null;
    local_download_id: number | null;
    local_version: string | null;
    reference_version: string | null;
  }>;
  checked_download_ids: number[];
};

export async function checkCollectionUpdates(
  collectionId: number,
): Promise<ApiCollectionUpdateCheck> {
  const baseUrl = await getBaseUrl();
  const res = await fetch(
    `${baseUrl}/api/collections/${collectionId}/check-updates`,
    { method: "POST" },
  );
  if (!res.ok) {
    await handleError(res, "POST", `/api/collections/${collectionId}/check-updates`);
  }
  return (await res.json()) as ApiCollectionUpdateCheck;
}
