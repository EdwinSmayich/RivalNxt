/**
 * Subtitles under a voice mod's .pak in a mod's Files tab.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { VoiceDownloadSubtitles, VoicePakSubtitles } from "../api";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("../api", () => ({
  getVoiceSubtitlesForDownloads: vi.fn(),
  makeVoiceSubtitles: vi.fn(),
  setActivePaks: vi.fn(),
  heroIconUrl: vi.fn(async (avatar: string) => `http://backend/hero-icons/${avatar}.png`),
}));

import * as api from "../api";
import { useVoicePakSubtitles, VoicePakSubtitlesRow } from "../../components/VoicePakSubtitles";

function Files({ pak = "Mods/LunaVoice_9999999_P.pak" }: { pak?: string }) {
  const state = useVoicePakSubtitles([5], true, "");
  return (
    <div>
      <VoicePakSubtitlesRow state={state} downloadId={5} pak={pak} />
      <VoicePakSubtitlesRow state={state} downloadId={5} pak="Textures_9999999_P.pak" />
    </div>
  );
}

function info(over: Partial<VoicePakSubtitles> = {}): VoicePakSubtitles {
  return {
    key: "abc123", name: "LunaVoice_9999999_P.pak", hero_name: "Luna Snow", avatar: "10310010", skipped: null,
    subtitles: { state: "ready", counts: { subtitled: 300, silenced: 20, kept: 0, missing: 0 }, models: [],
                 archive: "RU Subtitles - Luna Snow - LunaVoice.zip", archive_path: null, shared: false,
                 pak: "RU_Subtitles_LunaSnow_LunaVoice_9999999_P.pak", active: false, download_id: 42 },
    job: null,
    ...over,
  };
}

function answer(item: VoicePakSubtitles, over: Partial<VoiceDownloadSubtitles> = {}): VoiceDownloadSubtitles {
  return { language: "ru", language_name: "Russian", not_ready: null, scanning: false,
           paks: { "5": { "lunavoice_9999999_p.pak": item } }, ...over };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.setActivePaks).mockResolvedValue({} as never);
  vi.mocked(api.makeVoiceSubtitles).mockResolvedValue({} as never);
});

describe("VoicePakSubtitlesRow", () => {
  it("switches ready subtitles on beside their voice mod, and nothing for other files", async () => {
    vi.mocked(api.getVoiceSubtitlesForDownloads).mockResolvedValue(answer(info()));
    render(<Files />);
    expect(await screen.findByText("Russian subtitles · 300 lines")).toBeInTheDocument();
    expect(screen.getAllByRole("switch")).toHaveLength(1); // the texture mod gets no row
    fireEvent.click(screen.getByRole("switch", { name: "Subtitles on" }));
    await waitFor(() =>
      expect(api.setActivePaks).toHaveBeenCalledWith(42, ["RU_Subtitles_LunaSnow_LunaVoice_9999999_P.pak"]),
    );
    expect(api.getVoiceSubtitlesForDownloads).toHaveBeenCalledWith([5]);
  });

  it("makes them when there are none", async () => {
    const none = info({ subtitles: { ...info().subtitles, state: "none", counts: null, download_id: null } });
    vi.mocked(api.getVoiceSubtitlesForDownloads).mockResolvedValue(answer(none));
    render(<Files />);
    expect(await screen.findByText("No Russian subtitles yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Make subtitles/ }));
    await waitFor(() => expect(api.makeVoiceSubtitles).toHaveBeenCalledWith("abc123", "ru"));
  });

  it("says what is missing before they can be made", async () => {
    const none = info({ subtitles: { ...info().subtitles, state: "none", counts: null } });
    vi.mocked(api.getVoiceSubtitlesForDownloads).mockResolvedValue(
      answer(none, { not_ready: "Install speech recognition in the Voice Subtitles tab first" }),
    );
    render(<Files />);
    expect(await screen.findByText(/Install speech recognition/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Make subtitles/ })).toBeDisabled();
  });

  it("shows them being made", async () => {
    const making = info({
      subtitles: { ...info().subtitles, state: "none", counts: null },
      job: { id: "j", kind: "make", title: "", target: "abc123", language: "ru", state: "running",
             stage: "Translating", done: 30, total: 120, error: null, created_at: "", finished_at: null,
             seconds_left: null },
    });
    vi.mocked(api.getVoiceSubtitlesForDownloads).mockResolvedValue(answer(making));
    render(<Files />);
    expect(await screen.findByText("Making Russian subtitles · Translating 25%")).toBeInTheDocument();
  });

  it("says when a hero gets none", async () => {
    vi.mocked(api.getVoiceSubtitlesForDownloads).mockResolvedValue(answer(info({ skipped: "Peni Parker" })));
    render(<Files />);
    expect(await screen.findByText("Subtitles are not made for Luna Snow")).toBeInTheDocument();
  });
});
