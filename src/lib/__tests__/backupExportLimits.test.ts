/**
 * Backup export must degrade instead of failing, and loadouts must round-trip.
 *
 * The .json export embedded every custom image as full-resolution base64 into a
 * single JSON.stringify call. /api/mods/{id}/images returns originals (only the
 * list-preview endpoint downscales), so a large library produced a string past
 * V8's maximum length and the call threw "Invalid string length" -- the user got
 * an error toast and no backup file at all.
 *
 * Loadouts are the other half: recording only which paks were active makes
 * "disable everything, then put it all back" cheap enough to do on every toggle.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  AUTO_LOADOUT_ID,
  ImageBudget,
  MAX_EMBEDDED_IMAGE_CHARS,
  addLoadout,
  buildLoadout,
  computeLoadoutPlan,
  getLoadout,
  loadLoadouts,
  removeLoadout,
  serializeBackup,
  type ModBackup,
  type ModBackupEntry,
} from "../backupUtils";

const mockStorage = new Map<string, string>();
Object.defineProperty(global, "localStorage", {
  value: {
    getItem: (key: string) => mockStorage.get(key) ?? null,
    setItem: (key: string, value: string) => mockStorage.set(key, value.toString()),
    removeItem: (key: string) => mockStorage.delete(key),
    clear: () => mockStorage.clear(),
  },
  writable: true,
});

beforeEach(() => {
  localStorage.clear();
});

const img = (chars: number, filename = "a.png") => ({
  data: "x".repeat(chars),
  filename,
  mimeType: "image/png",
});

const entry = (over: Partial<ModBackupEntry> = {}): ModBackupEntry => ({
  modId: "1",
  backendModId: 1,
  name: "Mod",
  author: "",
  version: "",
  isActive: true,
  images: [],
  sourceDownloadIds: [1],
  sourceFileIds: [],
  ...over,
});

const backup = (mods: ModBackupEntry[]): ModBackup => ({
  id: "backup_1",
  name: "snapshot",
  createdAt: "2026-01-01T00:00:00.000Z",
  totalMods: mods.length,
  activeMods: mods.filter((m) => m.isActive).length,
  mods,
});

describe("ImageBudget", () => {
  it("keeps images that fit", () => {
    const budget = new ImageBudget(1000, 5000);
    expect(budget.take([img(400), img(400)])).toHaveLength(2);
    expect(budget.skippedCount).toBe(0);
  });

  it("skips a single image over the per-image limit", () => {
    const budget = new ImageBudget(1000, 100_000);
    const kept = budget.take([img(2000), img(100)]);
    expect(kept).toHaveLength(1);
    expect(kept[0].data).toHaveLength(100);
    expect(budget.skippedCount).toBe(1);
  });

  it("stops once the shared total is exhausted", () => {
    const budget = new ImageBudget(1000, 1500);
    expect(budget.take([img(800)])).toHaveLength(1);
    // Second call is a different mod, but the budget is shared across the export.
    expect(budget.take([img(800)])).toHaveLength(0);
    expect(budget.skippedCount).toBe(1);
    expect(budget.spentChars).toBe(800);
  });

  it("ignores empty payloads without charging the budget", () => {
    const budget = new ImageBudget(1000, 1000);
    expect(budget.take([{ data: "" }])).toHaveLength(0);
    expect(budget.spentChars).toBe(0);
    expect(budget.skippedCount).toBe(0);
  });

  it("defaults bound a realistic large library below the string ceiling", () => {
    // 177 mods, one oversized image each: the shape that used to throw.
    const budget = new ImageBudget();
    for (let i = 0; i < 177; i++) {
      budget.take([img(MAX_EMBEDDED_IMAGE_CHARS + 1)]);
    }
    expect(budget.spentChars).toBe(0);
    expect(budget.skippedCount).toBe(177);
  });
});

describe("serializeBackup", () => {
  it("produces parseable JSON and reports no loss", () => {
    const result = serializeBackup(backup([entry({ customImages: [img(10)] })]));
    expect(result.droppedImages).toBe(false);
    expect(JSON.parse(result.json).mods[0].customImages).toHaveLength(1);
  });

  it("omits the indent argument so exports stay compact", () => {
    // Pretty-printing adds megabytes of whitespace to a string already near the
    // engine limit, so the output must be minified.
    expect(serializeBackup(backup([entry()])).json).not.toContain("\n");
  });

  it("drops images rather than throwing when stringify hits the ceiling", () => {
    const target = backup([entry({ customImages: [img(10)] })]);
    const original = JSON.stringify;
    let calls = 0;
    try {
      // Simulate V8 refusing the first, image-bearing serialization.
      (JSON as any).stringify = (...args: unknown[]) => {
        if (calls++ === 0) throw new RangeError("Invalid string length");
        return (original as any)(...args);
      };
      const result = serializeBackup(target);
      expect(result.droppedImages).toBe(true);
      expect(JSON.parse(result.json).mods[0].customImages).toBeUndefined();
    } finally {
      JSON.stringify = original;
    }
  });

  it("rethrows failures that are not a length overflow", () => {
    const original = JSON.stringify;
    try {
      (JSON as any).stringify = () => {
        throw new TypeError("cyclic");
      };
      expect(() => serializeBackup(backup([entry()]))).toThrow(TypeError);
    } finally {
      JSON.stringify = original;
    }
  });
});

describe("buildLoadout", () => {
  it("records only downloads that have active paks", () => {
    const loadout = buildLoadout(
      [
        { id: 1, active_paks: ["a.pak", "b.pak"] },
        { id: 2, active_paks: [] },
        { id: 3, active_paks: null },
      ],
      "test",
    );
    expect(Object.keys(loadout.entries)).toEqual(["1"]);
    expect(loadout.activeDownloads).toBe(1);
    expect(loadout.activePaks).toBe(2);
  });

  it("carries no image or description payload", () => {
    const loadout = buildLoadout([{ id: 1, active_paks: ["a.pak"] }], "test");
    // A loadout must stay small enough for localStorage on every Disable All.
    expect(JSON.stringify(loadout).length).toBeLessThan(500);
  });
});

describe("loadout storage", () => {
  it("round-trips through localStorage", () => {
    const loadout = buildLoadout([{ id: 7, active_paks: ["x.pak"] }], "mine", AUTO_LOADOUT_ID);
    addLoadout(loadout);
    expect(getLoadout(AUTO_LOADOUT_ID)?.entries).toEqual({ "7": ["x.pak"] });
  });

  it("replaces rather than duplicates the auto slot", () => {
    addLoadout(buildLoadout([{ id: 1, active_paks: ["a.pak"] }], "first", AUTO_LOADOUT_ID));
    addLoadout(buildLoadout([{ id: 2, active_paks: ["b.pak"] }], "second", AUTO_LOADOUT_ID));
    expect(loadLoadouts()).toHaveLength(1);
    expect(getLoadout(AUTO_LOADOUT_ID)?.entries).toEqual({ "2": ["b.pak"] });
  });

  it("removes a slot by id", () => {
    addLoadout(buildLoadout([{ id: 1, active_paks: ["a.pak"] }], "x", AUTO_LOADOUT_ID));
    removeLoadout(AUTO_LOADOUT_ID);
    expect(getLoadout(AUTO_LOADOUT_ID)).toBeNull();
  });

  it("survives corrupt storage", () => {
    localStorage.setItem("rivalnxt:loadouts", "{not json");
    expect(loadLoadouts()).toEqual([]);
  });

  it("an empty capture must not be persisted over a good loadout", () => {
    // Regression: capture used to persist unconditionally, so a second Disable
    // All (when everything was already off) overwrote the saved slot with an
    // empty one and Restore silently became a no-op. The caller now persists
    // only a non-empty capture; this asserts the shape that guard relies on.
    addLoadout(buildLoadout([{ id: 1, active_paks: ["a.pak"] }], "good", AUTO_LOADOUT_ID));
    const emptyCapture = buildLoadout([{ id: 1, active_paks: [] }], "nothing-active", AUTO_LOADOUT_ID);
    expect(emptyCapture.activeDownloads).toBe(0);

    expect(getLoadout(AUTO_LOADOUT_ID)?.entries).toEqual({ "1": ["a.pak"] });
  });
});

describe("computeLoadoutPlan", () => {
  const loadout = buildLoadout(
    [
      { id: 1, active_paks: ["a.pak"] },
      { id: 2, active_paks: ["b.pak", "c.pak"] },
    ],
    "saved",
  );

  it("re-enables everything after a disable-all", () => {
    const plan = computeLoadoutPlan(loadout, [
      { id: 1, active_paks: [] },
      { id: 2, active_paks: [] },
    ]);
    expect(plan).toEqual([
      { downloadId: 1, paks: ["a.pak"] },
      { downloadId: 2, paks: ["b.pak", "c.pak"] },
    ]);
  });

  it("clears downloads that are active but absent from the loadout", () => {
    // Otherwise restoring a smaller loadout would leave strays enabled.
    const plan = computeLoadoutPlan(loadout, [
      { id: 1, active_paks: ["a.pak"] },
      { id: 2, active_paks: ["b.pak", "c.pak"] },
      { id: 9, active_paks: ["stray.pak"] },
    ]);
    expect(plan).toEqual([{ downloadId: 9, paks: [] }]);
  });

  it("is a no-op when live state already matches, regardless of pak order", () => {
    const plan = computeLoadoutPlan(loadout, [
      { id: 1, active_paks: ["a.pak"] },
      { id: 2, active_paks: ["c.pak", "b.pak"] },
    ]);
    expect(plan).toEqual([]);
  });

  it("skips mods from the loadout that are no longer installed", () => {
    const plan = computeLoadoutPlan(loadout, [{ id: 1, active_paks: ["a.pak"] }]);
    expect(plan).toEqual([]);
  });
});
