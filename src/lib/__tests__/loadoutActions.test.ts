/**
 * Disable-all / restore is driven from two places (the global header and the
 * Backup modal), so the logic lives in one module and is tested here rather
 * than through either component.
 *
 * The invariant that matters most: Disable All must never destroy the loadout
 * it is supposed to be protecting.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  scanActive: vi.fn(async () => ({ ok: true })),
  refreshConflicts: vi.fn(async () => ({ ok: true })),
  setActivePaks: vi.fn(async () => ({ ok: true })),
  listDownloads: vi.fn(async () => [] as any[]),
  getLocalDownload: vi.fn(async () => ({ contents: [] as string[] })),
}));

vi.mock("../api", () => api);

const mockStorage = new Map<string, string>();
Object.defineProperty(global, "localStorage", {
  value: {
    getItem: (k: string) => mockStorage.get(k) ?? null,
    setItem: (k: string, v: string) => mockStorage.set(k, String(v)),
    removeItem: (k: string) => mockStorage.delete(k),
    clear: () => mockStorage.clear(),
  },
  writable: true,
});

import { AUTO_LOADOUT_ID, addLoadout, buildLoadout, getLoadout } from "../backupUtils";
import {
  deletePreset,
  disableAllRemembering,
  findActivePreset,
  getRememberedLoadout,
  listPresets,
  restoreLoadout,
  savePreset,
} from "../loadoutActions";

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  api.listDownloads.mockResolvedValue([]);
  api.getLocalDownload.mockResolvedValue({ contents: [] });
});

describe("disableAllRemembering", () => {
  it("records the loadout and switches every active download off", async () => {
    api.listDownloads.mockResolvedValue([
      { id: 1, active_paks: ["a.pak"] },
      { id: 2, active_paks: ["b.pak", "c.pak"] },
      { id: 3, active_paks: [] },
    ]);

    const { disabled, loadout } = await disableAllRemembering();

    expect(disabled).toBe(2);
    expect(loadout.activePaks).toBe(3);
    expect(api.setActivePaks).toHaveBeenCalledWith(1, []);
    expect(api.setActivePaks).toHaveBeenCalledWith(2, []);
    // The already-inactive download is left alone.
    expect(api.setActivePaks).not.toHaveBeenCalledWith(3, []);
    expect(getLoadout(AUTO_LOADOUT_ID)?.entries).toEqual({
      "1": ["a.pak"],
      "2": ["b.pak", "c.pak"],
    });
  });

  it("does not overwrite a saved loadout when nothing is active", async () => {
    addLoadout(buildLoadout([{ id: 1, active_paks: ["a.pak"] }], "good", AUTO_LOADOUT_ID));
    api.listDownloads.mockResolvedValue([{ id: 1, active_paks: [] }]);

    const { disabled } = await disableAllRemembering();

    expect(disabled).toBe(0);
    expect(api.setActivePaks).not.toHaveBeenCalled();
    // Clicking Disable All twice must not turn Restore into a no-op.
    expect(getLoadout(AUTO_LOADOUT_ID)?.entries).toEqual({ "1": ["a.pak"] });
  });
});

describe("restoreLoadout", () => {
  it("re-enables exactly the remembered paks", async () => {
    const loadout = buildLoadout(
      [
        { id: 1, active_paks: ["a.pak"] },
        { id: 2, active_paks: ["b.pak"] },
      ],
      "saved",
      AUTO_LOADOUT_ID,
    );
    addLoadout(loadout);
    api.listDownloads.mockResolvedValue([
      { id: 1, active_paks: [] },
      { id: 2, active_paks: [] },
    ]);

    const { updated, missing } = await restoreLoadout();

    expect(updated).toBe(2);
    expect(missing).toBe(0);
    expect(api.setActivePaks).toHaveBeenCalledWith(1, ["a.pak"]);
    expect(api.setActivePaks).toHaveBeenCalledWith(2, ["b.pak"]);
  });

  it("switches off anything enabled since the snapshot", async () => {
    addLoadout(buildLoadout([{ id: 1, active_paks: ["a.pak"] }], "saved", AUTO_LOADOUT_ID));
    api.listDownloads.mockResolvedValue([
      { id: 1, active_paks: ["a.pak"] },
      { id: 9, active_paks: ["stray.pak"] },
    ]);

    const { updated } = await restoreLoadout();

    expect(updated).toBe(1);
    expect(api.setActivePaks).toHaveBeenCalledWith(9, []);
  });

  it("counts mods that are no longer installed", async () => {
    addLoadout(
      buildLoadout(
        [
          { id: 1, active_paks: ["a.pak"] },
          { id: 2, active_paks: ["b.pak"] },
        ],
        "saved",
        AUTO_LOADOUT_ID,
      ),
    );
    api.listDownloads.mockResolvedValue([{ id: 1, active_paks: [] }]);

    const { updated, missing } = await restoreLoadout();

    expect(updated).toBe(1);
    expect(missing).toBe(1);
  });

  it("skips the filesystem resync when nothing changed", async () => {
    addLoadout(buildLoadout([{ id: 1, active_paks: ["a.pak"] }], "saved", AUTO_LOADOUT_ID));
    api.listDownloads.mockResolvedValue([{ id: 1, active_paks: ["a.pak"] }]);

    const { updated } = await restoreLoadout();

    expect(updated).toBe(0);
    expect(api.setActivePaks).not.toHaveBeenCalled();
    expect(api.refreshConflicts).not.toHaveBeenCalled();
  });

  it("rejects when there is nothing remembered", async () => {
    await expect(restoreLoadout()).rejects.toThrow(/no remembered loadout/i);
  });
});

describe("getRememberedLoadout", () => {
  it("treats an empty loadout as nothing to offer", () => {
    addLoadout(buildLoadout([{ id: 1, active_paks: [] }], "empty", AUTO_LOADOUT_ID));
    // The header button hides on null rather than offering a restore that
    // would disable everything.
    expect(getRememberedLoadout()).toBeNull();
  });

  it("returns a real loadout", () => {
    addLoadout(buildLoadout([{ id: 1, active_paks: ["a.pak"] }], "real", AUTO_LOADOUT_ID));
    expect(getRememberedLoadout()?.activeDownloads).toBe(1);
  });
});

describe("presets", () => {
  it("saves the current selection under a name", async () => {
    api.listDownloads.mockResolvedValue([
      { id: 1, active_paks: ["a.pak"] },
      { id: 2, active_paks: ["b.pak"] },
    ]);

    const saved = await savePreset("PvP");

    expect(saved?.name).toBe("PvP");
    expect(saved?.activeDownloads).toBe(2);
    expect(listPresets().map((p) => p.name)).toEqual(["PvP"]);
  });

  it("refuses to save an empty preset", async () => {
    // Applying one would silently disable everything, which is never what
    // "save my current setup" is supposed to mean.
    api.listDownloads.mockResolvedValue([{ id: 1, active_paks: [] }]);
    expect(await savePreset("Nothing")).toBeNull();
    expect(listPresets()).toEqual([]);
  });

  it("rejects a blank name", async () => {
    await expect(savePreset("   ")).rejects.toThrow(/cannot be empty/i);
  });

  it("re-saving the same name replaces it rather than duplicating", async () => {
    api.listDownloads.mockResolvedValue([{ id: 1, active_paks: ["a.pak"] }]);
    await savePreset("PvP");
    api.listDownloads.mockResolvedValue([
      { id: 1, active_paks: ["a.pak"] },
      { id: 2, active_paks: ["b.pak"] },
    ]);
    await savePreset("PvP");

    const all = listPresets();
    expect(all).toHaveLength(1);
    expect(all[0].activeDownloads).toBe(2);
  });

  it("keeps presets separate from the automatic Disable All slot", async () => {
    api.listDownloads.mockResolvedValue([{ id: 1, active_paks: ["a.pak"] }]);
    await savePreset("PvP");
    await disableAllRemembering();

    // The auto-capture must not appear among presets, nor clobber one.
    expect(listPresets().map((p) => p.name)).toEqual(["PvP"]);
    expect(getRememberedLoadout()?.activeDownloads).toBe(1);
  });

  it("applies a preset through the same plan as a restore", async () => {
    api.listDownloads.mockResolvedValue([{ id: 1, active_paks: ["a.pak"] }]);
    const preset = await savePreset("PvP");
    api.listDownloads.mockResolvedValue([{ id: 1, active_paks: [] }]);

    const { updated } = await restoreLoadout(preset);

    expect(updated).toBe(1);
    expect(api.setActivePaks).toHaveBeenCalledWith(1, ["a.pak"]);
  });

  it("deletes a preset by id", async () => {
    api.listDownloads.mockResolvedValue([{ id: 1, active_paks: ["a.pak"] }]);
    const preset = await savePreset("Temp");
    deletePreset(preset!.id);
    expect(listPresets()).toEqual([]);
  });
});
describe("findActivePreset", () => {
  const preset = (name: string, entries: Record<string, string[]>) => ({
    id: `preset:${name}`,
    name,
    createdAt: "2026-01-01T00:00:00.000Z",
    entries,
    activeDownloads: Object.keys(entries).length,
    activePaks: Object.values(entries).flat().length,
  });

  it("finds the preset matching what is enabled", () => {
    const pvp = preset("PvP", { "1": ["a.pak"], "2": ["b.pak"] });
    const other = preset("Other", { "1": ["a.pak"] });
    const live = [
      { id: 1, active_paks: ["a.pak"] },
      { id: 2, active_paks: ["b.pak"] },
    ];
    expect(findActivePreset(live, [other, pvp])?.name).toBe("PvP");
  });

  it("ignores pak order", () => {
    const p = preset("P", { "1": ["a.pak", "b.pak"] });
    expect(findActivePreset([{ id: 1, active_paks: ["b.pak", "a.pak"] }], [p])?.name).toBe("P");
  });

  it("an extra enabled mod means no preset is active", () => {
    // "Close enough" would claim a preset that is not actually loaded.
    const p = preset("P", { "1": ["a.pak"] });
    const live = [
      { id: 1, active_paks: ["a.pak"] },
      { id: 9, active_paks: ["stray.pak"] },
    ];
    expect(findActivePreset(live, [p])).toBeNull();
  });

  it("a missing mod means no preset is active", () => {
    const p = preset("P", { "1": ["a.pak"], "2": ["b.pak"] });
    expect(findActivePreset([{ id: 1, active_paks: ["a.pak"] }], [p])).toBeNull();
  });

  it("a different pak variant of the same mod does not match", () => {
    const p = preset("P", { "1": ["a.pak"] });
    expect(findActivePreset([{ id: 1, active_paks: ["different.pak"] }], [p])).toBeNull();
  });

  it("returns null when nothing is enabled", () => {
    const p = preset("P", { "1": ["a.pak"] });
    expect(findActivePreset([{ id: 1, active_paks: [] }], [p])).toBeNull();
  });

  it("returns null when there are no presets", () => {
    expect(findActivePreset([{ id: 1, active_paks: ["a.pak"] }], [])).toBeNull();
  });
});
