import { describe, expect, it } from "vitest";

import { isSubtitleModArchive } from "../subtitleMods";

describe("isSubtitleModArchive", () => {
  it("knows the archives the Voice Subtitles tab writes", () => {
    expect(isSubtitleModArchive("RU Subtitles - Luna Snow - LunaVoice.zip")).toBe(true);
    expect(isSubtitleModArchive("D:\\Mods\\LAS Subtitles - Storm - Voice S9.zip")).toBe(true);
    expect(isSubtitleModArchive("mods/CHS Subtitles - Hela - Voice.zip")).toBe(true);
    // As the library stores a file someone passed on.
    expect(isSubtitleModArchive("RU_Subtitles_-_Luna_Snow_-_LunaVoice.zip")).toBe(true);
  });

  it("leaves other mods alone", () => {
    expect(isSubtitleModArchive("Luna Snow Voice-1234-1-0-1700000000.zip")).toBe(false);
    expect(isSubtitleModArchive("FX Subtitles - Overhaul.zip")).toBe(false);
    expect(isSubtitleModArchive("RU Subtitles - Storm - Voice.rar")).toBe(false);
    expect(isSubtitleModArchive(undefined)).toBe(false);
  });
});
