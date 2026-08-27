/**
 * The Backup screen used to show two panels — "Restore Backup" and "Quick
 * Loadout" — each with its own Restore button and no explanation anywhere of
 * how they differed. Reported verbatim: "I honestly don't see much point in
 * separate tabs... I don't understand the difference."
 *
 * They are now one list ordered by when each save was taken. The difference is
 * real (an archive carries the whole database, a loadout only records which pak
 * files were on) so it survives as a label on the row, not as a separate panel.
 */
import { describe, expect, it } from "vitest";
import {
  buildRestorePoints,
  fromServerBackup,
  RESTORE_POINT_SCOPE,
  type Loadout,
  type ServerBackupInfo,
  type UnifiedBackup,
} from "../backupUtils";

const archive = (over: Partial<ServerBackupInfo> = {}): UnifiedBackup => {
  const base: ServerBackupInfo = {
    name: "Snapshot",
    path: "C:/data/backups/snap.zip",
    created_at: "2026-02-01T10:00:00.000Z",
    size_bytes: 87_000_000,
    manifest_version: 2,
    total_mods: 213,
    active_mods: 76,
    kind: "manual",
    description: "Snapshot you created from the Backup screen.",
  };
  return fromServerBackup({ ...base, ...over });
};

const loadout = (over: Partial<Loadout> = {}): Loadout => ({
  id: "auto:last-disable-all",
  name: "Before Disable All",
  createdAt: "2026-02-01T12:00:00.000Z",
  entries: { "1": ["a.pak"], "2": ["b.pak", "c.pak"] },
  activeDownloads: 2,
  activePaks: 3,
  ...over,
});

describe("buildRestorePoints", () => {
  it("puts backups and the loadout in one list, newest first", () => {
    const points = buildRestorePoints(
      [
        archive({ path: "old.zip", created_at: "2026-01-01T00:00:00.000Z" }),
        archive({ path: "new.zip", created_at: "2026-03-01T00:00:00.000Z" }),
      ],
      loadout(), // 2026-02-01, i.e. between the two
    );
    expect(points.map((p) => p.kind)).toEqual(["full", "loadout", "full"]);
  });

  it("the newest entry is what Restore latest will use", () => {
    const points = buildRestorePoints(
      [archive({ created_at: "2026-01-01T00:00:00.000Z" })],
      loadout({ createdAt: "2026-05-01T00:00:00.000Z" }),
    );
    expect(points[0].kind).toBe("loadout");
  });

  it("labels each kind so the row says what it reaches", () => {
    const points = buildRestorePoints([archive()], loadout());
    for (const point of points) {
      expect(RESTORE_POINT_SCOPE[point.kind]).toBeTruthy();
    }
    // The distinction the two panels never actually stated.
    expect(RESTORE_POINT_SCOPE.full).toMatch(/whole library/i);
    expect(RESTORE_POINT_SCOPE.loadout).toMatch(/nothing else/i);
  });

  it("an empty loadout is not offered", () => {
    // Restoring one would disable every mod and look like the app broke.
    const points = buildRestorePoints(
      [archive()],
      loadout({ activeDownloads: 0, activePaks: 0, entries: {} }),
    );
    expect(points.map((p) => p.kind)).toEqual(["full"]);
  });

  it("no loadout at all is fine", () => {
    expect(buildRestorePoints([archive()], null)).toHaveLength(1);
  });

  it("nothing saved yields an empty list rather than throwing", () => {
    expect(buildRestorePoints([], null)).toEqual([]);
  });

  it("carries the archive through so Restore knows which file to open", () => {
    const point = buildRestorePoints([archive({ path: "C:/x/y.zip" })], null)[0];
    expect(point.backup?.filePath).toBe("C:/x/y.zip");
    expect(point.loadout).toBeUndefined();
  });

  it("carries the loadout through so Restore knows which paks to re-enable", () => {
    const point = buildRestorePoints([], loadout())[0];
    expect(point.loadout?.entries).toEqual({ "1": ["a.pak"], "2": ["b.pak", "c.pak"] });
    expect(point.backup).toBeUndefined();
  });

  it("summarises a backup by its mod counts", () => {
    expect(buildRestorePoints([archive()], null)[0].summary).toBe("213 mods (76 active)");
  });

  it("summarises a loadout by what it will switch back on", () => {
    expect(buildRestorePoints([], loadout())[0].summary).toBe("2 mods · 3 pak files");
  });

  it("says 'pak file' for exactly one", () => {
    const one = loadout({ activeDownloads: 1, activePaks: 1, entries: { "1": ["a.pak"] } });
    expect(buildRestorePoints([], one)[0].summary).toBe("1 mods · 1 pak file");
  });

  it("a .json export is distinguished from a full archive", () => {
    // It cannot restore artwork, so offering it under the same label would
    // promise more than it delivers.
    const legacy: UnifiedBackup = {
      ...archive(),
      generation: 1,
      restorableViaApi: false,
    };
    expect(buildRestorePoints([legacy], null)[0].kind).toBe("export");
    expect(RESTORE_POINT_SCOPE.export).toMatch(/no artwork/i);
  });

  it("an archive with no date still appears rather than vanishing", () => {
    // Older manifests wrote created_at: null. Sorting must not drop the row.
    const points = buildRestorePoints([archive({ created_at: undefined })], loadout());
    expect(points).toHaveLength(2);
    expect(points[0].kind).toBe("loadout");
  });

  it("falls back to the description when a backup has no mod counts", () => {
    const point = buildRestorePoints(
      [archive({ total_mods: 0, active_mods: 0, description: "Taken before restoring." })],
      null,
    )[0];
    expect(point.summary).toBe("Taken before restoring.");
  });
});
