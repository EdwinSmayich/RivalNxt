/**
 * The Voice Subtitles tab: what it offers at each step, and what its buttons ask the backend for.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { VoiceJob, VoiceLine, VoiceMod, VoiceSubtitlesStatus } from "../api";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("../api", () => ({
  getVoiceSubtitles: vi.fn(),
  setVoiceSubtitlesSettings: vi.fn(),
  installVoiceComponent: vi.fn(),
  removeVoiceComponent: vi.fn(),
  rescanVoiceMods: vi.fn(),
  makeVoiceSubtitles: vi.fn(),
  makeAllVoiceSubtitles: vi.fn(),
  cancelVoiceJob: vi.fn(),
  setActivePaks: vi.fn(),
  getVoiceLines: vi.fn(),
  editVoiceLine: vi.fn(),
}));

import * as api from "../api";
import VoiceSubtitlesPage, { timeLeft } from "../../components/VoiceSubtitlesPage";

function voiceMod(over: Partial<VoiceMod> = {}): VoiceMod {
  return {
    key: "abc123",
    name: "LunaVoice_9999999_P.pak",
    bank: "bnk_vo_1031001.bnk",
    bank_id: "1031001",
    hero: "1031",
    hero_name: "Luna Snow",
    installed: ["luna_snow/LunaVoice_9999999_P.pak"],
    library: [],
    skipped: null,
    subtitles: {
      ru: { state: "none", counts: null, models: [], archive: "RU Subtitles - Luna Snow - LunaVoice.zip",
            pak: "RU_Subtitles_LunaSnow_LunaVoice_9999999_P.pak", active: false, download_id: null },
    },
    ...over,
  };
}

const MODELS = [
  { id: "gemma-4-31b", title: "Gemma 4 31B, compact", quality: "Best", blurb: "", size: 14e9,
    fit: "gpu" as const, installed: false, recommended: true },
  { id: "gemma-4-12b", title: "Gemma 4 12B", quality: "Good", blurb: "", size: 8e9,
    fit: "gpu" as const, installed: false, recommended: false },
];

function status(over: Partial<VoiceSubtitlesStatus> = {}): VoiceSubtitlesStatus {
  return {
    folder: "D:\\Voice", free_bytes: 500e9, game_found: true, game_running: false,
    downloads_folder: "F:\\mods", mods_folder: "G:\\Game\\~mods",
    game_language: "ru", language: "ru", language_set: false,
    languages: [{ code: "en", name: "English" }, { code: "ru", name: "Russian" }],
    hardware: { gpus: [{ name: "GeForce RTX 5080", vendor: "nvidia", vram_mb: 16303, cuda: 13 }], ram_mb: 63000, threads: 32 },
    recognition: { installed: false, size: 0.9e9, gpu: { available: true, installed: false, on: false, size: 0.68e9 } },
    translation: { model: null, ready: false, engine: "llama-cuda13", recommended: "gemma-4-31b", models: MODELS },
    voice_mods: [voiceMod()], scanning: false, scan_note: "", jobs: [], combined: {},
    ...over,
  };
}

const ready = (over: Partial<VoiceSubtitlesStatus> = {}) =>
  status({
    recognition: { installed: true, size: 0, gpu: { available: true, installed: false, on: false, size: 0.68e9 } },
    translation: { ...status().translation, model: "gemma-4-31b", ready: true,
                   models: [{ ...MODELS[0], installed: true }, MODELS[1]] },
    ...over,
  });

function job(over: Partial<VoiceJob> = {}): VoiceJob {
  return {
    id: "j1", kind: "make", title: "Luna Snow · LunaVoice", target: "abc123", language: "ru",
    state: "running", stage: "Translating", done: 50, total: 200, error: null, created_at: "", finished_at: null,
    seconds_left: null, ...over,
  };
}

const madeRu = (over: Partial<VoiceMod["subtitles"]["ru"]> = {}) =>
  voiceMod({
    subtitles: { ru: { ...voiceMod().subtitles.ru, state: "ready", download_id: 42, models: ["gemma-4-31b"],
                       counts: { subtitled: 300, silenced: 120, kept: 2, missing: 0 }, ...over } },
  });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.makeVoiceSubtitles).mockResolvedValue({} as VoiceJob);
  vi.mocked(api.makeAllVoiceSubtitles).mockResolvedValue({ jobs: [] });
  vi.mocked(api.setActivePaks).mockResolvedValue({} as never);
  vi.mocked(api.cancelVoiceJob).mockResolvedValue({ ok: true });
  vi.mocked(api.installVoiceComponent).mockResolvedValue({} as VoiceJob);
});

describe("VoiceSubtitlesPage", () => {
  it("starts with installing speech recognition", async () => {
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(status());
    render(<VoiceSubtitlesPage />);
    const install = await screen.findByRole("button", { name: /Install \(0\.9 GB\)/ });
    expect(screen.getByRole("button", { name: /Make subtitles/ })).toBeDisabled();
    fireEvent.click(install);
    await waitFor(() => expect(api.installVoiceComponent).toHaveBeenCalledWith("recognition"));
  });

  it("shows the download in place of the install button", async () => {
    const download = job({ kind: "install", title: "Speech recognition", target: "vgmstream,whisper-cpu,whisper-model",
                           stage: "Downloading Whisper", done: 0.45e9, total: 0.9e9, seconds_left: 125 });
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(status({ jobs: [download] }));
    render(<VoiceSubtitlesPage />);
    expect(await screen.findByText(/Downloading Whisper · 0\.5 GB of 0\.9 GB · about 2 min left/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Install \(/ })).toBeNull();
  });

  it("offers the recommended translation model", async () => {
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(
      status({ recognition: { installed: true, size: 0, gpu: { available: false, installed: false, on: false, size: 0 } } }),
    );
    render(<VoiceSubtitlesPage />);
    expect(await screen.findByText("Recommended")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Install Gemma 4 31B, compact/ }));
    await waitFor(() => expect(api.installVoiceComponent).toHaveBeenCalledWith("gemma-4-31b"));
  });

  it("folds the model list away once a model is in use", async () => {
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(ready());
    render(<VoiceSubtitlesPage />);
    expect(await screen.findByText("In use")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Translation model" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Change model" }));
    const list = screen.getByRole("radiogroup", { name: "Translation model" });
    fireEvent.click(within(list).getByText("Gemma 4 12B"));
    fireEvent.click(screen.getByRole("button", { name: /Install Gemma 4 12B/ }));
    await waitFor(() => expect(api.installVoiceComponent).toHaveBeenCalledWith("gemma-4-12b"));
  });

  it("makes subtitles for a voice mod in the chosen language", async () => {
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(ready());
    render(<VoiceSubtitlesPage />);
    expect(await screen.findByText("Luna Snow")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Make subtitles/ }));
    await waitFor(() => expect(api.makeVoiceSubtitles).toHaveBeenCalledWith("abc123", "ru"));
  });

  it("makes all that are not made yet", async () => {
    const other = voiceMod({ key: "def456", name: "StormVoice_9999999_P.pak", hero: "1015", hero_name: "Storm" });
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(ready({ voice_mods: [voiceMod(), other, { ...madeRu(), key: "x" }] }));
    render(<VoiceSubtitlesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Make all (2)" }));
    await waitFor(() => expect(api.makeAllVoiceSubtitles).toHaveBeenCalledWith("ru"));
  });

  it("finds a voice mod by hero or name", async () => {
    const mods = ["Storm", "Hela", "Mantis", "Psylocke", "Magik", "Loki"].map((hero, i) =>
      voiceMod({ key: `k${i}`, hero_name: hero, name: `${hero}Voice_9999999_P.pak` }),
    );
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(ready({ voice_mods: mods }));
    render(<VoiceSubtitlesPage />);
    fireEvent.change(await screen.findByRole("textbox", { name: "Search voice mods" }), { target: { value: "hel" } });
    expect(screen.getByText("Hela")).toBeInTheDocument();
    expect(screen.queryByText("Storm")).toBeNull();
  });

  it("switches a finished subtitle mod on through the library", async () => {
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(ready({ voice_mods: [madeRu()] }));
    render(<VoiceSubtitlesPage />);
    expect(await screen.findByText(/300 lines · 120 silenced · 2 keep the game's/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Translate again/ })).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: "Subtitle mod on" }));
    await waitFor(() =>
      expect(api.setActivePaks).toHaveBeenCalledWith(42, ["RU_Subtitles_LunaSnow_LunaVoice_9999999_P.pak"]),
    );
  });

  it("offers to translate again with the model now in use", async () => {
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(ready({ voice_mods: [madeRu({ models: ["gemma-4-12b"] })] }));
    render(<VoiceSubtitlesPage />);
    expect(await screen.findByText("Translated by Gemma 4 12B")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Translate again/ }));
    await waitFor(() => expect(api.makeVoiceSubtitles).toHaveBeenCalledWith("abc123", "ru"));
  });

  it("does not offer a smaller model's translation in place of a better one", async () => {
    const smaller = ready().translation;
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(
      ready({
        translation: { ...smaller, model: "gemma-4-12b", models: smaller.models.map((m) => ({ ...m, installed: true })) },
        voice_mods: [madeRu({ models: ["gemma-4-31b"] })],
      }),
    );
    render(<VoiceSubtitlesPage />);
    expect(await screen.findByText("Translated by Gemma 4 31B, compact")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Translate again/ })).toBeNull();
  });

  it("shows a running job and can cancel it", async () => {
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(ready({ jobs: [job()] }));
    render(<VoiceSubtitlesPage />);
    expect(await screen.findByText("25%")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Make subtitles/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Cancel/ }));
    await waitFor(() => expect(api.cancelVoiceJob).toHaveBeenCalledWith("j1"));
  });

  it("says when the game holds the work back", async () => {
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(
      ready({ game_running: true, jobs: [job({ state: "waiting", stage: "Waiting for the game to close" })] }),
    );
    render(<VoiceSubtitlesPage />);
    expect(await screen.findByText(/Marvel Rivals is running/)).toBeInTheDocument();
  });

  it("explains subtitles in a language other than the game's", async () => {
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(ready({ language: "en", language_set: true }));
    render(<VoiceSubtitlesPage />);
    expect(await screen.findByText(/English subtitle mods show in it as well/)).toBeInTheDocument();
    expect(screen.getByText(/Not needed: English subtitles are the words heard/)).toBeInTheDocument();
  });

  it("says when a hero's voice mods get no subtitles", async () => {
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(ready({ voice_mods: [voiceMod({ skipped: "Peni Parker" })] }));
    render(<VoiceSubtitlesPage />);
    expect(await screen.findByText("Not made for this hero")).toBeInTheDocument();
  });

  it("reviews the spoken lines first and saves an edit", async () => {
    const line = (over: Partial<VoiceLine>): VoiceLine => ({
      key: "k1", status: "changed", game: "Привет!", game_en: "Hello!", heard: "Hi, darling.",
      subtitle: "Привет, милый.", edited: false, left_as_in_game: false, ...over,
    });
    vi.mocked(api.getVoiceSubtitles).mockResolvedValue(ready({ voice_mods: [madeRu()] }));
    vi.mocked(api.getVoiceLines).mockResolvedValue({
      lines: [line({ key: "s1", status: "silent", heard: "", subtitle: "" }), line({})],
    });
    vi.mocked(api.editVoiceLine).mockResolvedValue({ counts: null });
    render(<VoiceSubtitlesPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Review/ }));
    const input = await screen.findByRole("textbox", { name: "Subtitle" }); // only the spoken line
    expect(input).toHaveValue("Привет, милый.");
    fireEvent.change(input, { target: { value: "Привет, дорогой." } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    await waitFor(() => expect(api.editVoiceLine).toHaveBeenCalledWith("abc123", "ru", "k1", "Привет, дорогой."));
  });
});

describe("timeLeft", () => {
  it("rounds to what a person reads", () => {
    expect(timeLeft(20)).toBe("less than a minute left");
    expect(timeLeft(125)).toBe("about 2 min left");
    expect(timeLeft(3 * 3600 + 25 * 60)).toBe("about 3 h 25 min left");
  });
});
