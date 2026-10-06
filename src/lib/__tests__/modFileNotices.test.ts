/**
 * A mod switched off while the game runs leaves files the game still has open.
 *
 * The backend used to swallow that; it now answers with a `warning`. The
 * warning is shown from inside `setActivePaks` itself, because there are twenty
 * places that call it and none of them looked at the answer.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const warning = vi.fn();
vi.mock("sonner", () => ({ toast: { warning: (...args: unknown[]) => warning(...args) } }));

import {
  MOD_FILE_NOTICE_TOAST_ID,
  showModFileWarning,
  warningFrom,
} from "../modFileNotices";

const LOCKED =
  "The mod is off, but the game still has 1 of its files open. They take no part in the game and will be removed once it is closed.";

beforeEach(() => warning.mockClear());

describe("warningFrom", () => {
  it("reads the warning out of a response", () => {
    expect(warningFrom({ ok: true, locked: ["Mod_P.ucas"], warning: LOCKED })).toBe(LOCKED);
  });

  it("is null for an ordinary response", () => {
    expect(warningFrom({ ok: true, locked: [] })).toBeNull();
  });

  it("ignores a blank or non-text warning", () => {
    expect(warningFrom({ warning: "   " })).toBeNull();
    expect(warningFrom({ warning: 3 })).toBeNull();
    expect(warningFrom({ warning: null })).toBeNull();
  });

  it("is safe on anything that is not a response", () => {
    expect(warningFrom(null)).toBeNull();
    expect(warningFrom(undefined)).toBeNull();
    expect(warningFrom("text")).toBeNull();
  });
});

describe("showModFileWarning", () => {
  it("shows the backend's own words", () => {
    expect(showModFileWarning({ ok: true, warning: LOCKED })).toBe(true);
    expect(warning).toHaveBeenCalledTimes(1);
    expect(warning.mock.calls[0][1]).toMatchObject({ description: LOCKED });
  });

  it("stays silent when there is nothing to say", () => {
    expect(showModFileWarning({ ok: true })).toBe(false);
    expect(warning).not.toHaveBeenCalled();
  });

  it("uses one toast for a whole batch", () => {
    // Switching a collection off sends a request per mod.
    showModFileWarning({ warning: LOCKED });
    showModFileWarning({ warning: LOCKED });
    const ids = warning.mock.calls.map((call) => (call[1] as { id: string }).id);
    expect(new Set(ids)).toEqual(new Set([MOD_FILE_NOTICE_TOAST_ID]));
  });
});

describe("where it is wired in", () => {
  const read = (...parts: string[]) =>
    readFileSync(join(__dirname, "..", "..", ...parts), "utf8");

  it("every activation goes through it", () => {
    const api = read("lib", "api.ts");
    const fn = api.slice(
      api.indexOf("export async function setActivePaks("),
      api.indexOf("export interface DisableAllModsResult"),
    );
    expect(fn).toContain("showModFileWarning(result)");
    expect(fn).toContain("return result;");
  });

  it("'disable all' says where mods it did not install were moved to", () => {
    const modal = read("components", "CrashDetectorModal.tsx");
    const handler = modal.slice(
      modal.indexOf("const handleDisableAll"),
      modal.indexOf("if (!crashInfo) return null;"),
    );
    expect(handler).toContain("result.moved_out");
    expect(handler).toContain("description: result.warning");
  });

  it("and does not claim success for mods that are still loaded", () => {
    const modal = read("components", "CrashDetectorModal.tsx");
    const handler = modal.slice(
      modal.indexOf("const handleDisableAll"),
      modal.indexOf("if (!crashInfo) return null;"),
    );
    const stillOn = handler.slice(
      handler.indexOf("result.still_on"),
      handler.indexOf("} else if (result.moved_out"),
    );
    expect(stillOn).toContain("toast.warning");
    expect(stillOn).not.toContain("toast.success");
  });
});
