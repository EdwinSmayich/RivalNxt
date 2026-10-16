/**
 * A subtitle mod made by the Voice Subtitles tab has no Nexus page: its card
 * does not ask for a mod id or an author.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../components/NSFWFilterProvider", () => ({ useNsfwFilter: () => ({ nsfwBlurEnabled: false }) }));
// jsdom scrolls nothing into view: show the card's content straight away.
vi.mock("../../components/LazyLoad", () => ({
  LazyLoad: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import { InstalledModCard } from "../../components/InstalledModCard";
import type { Mod } from "../../components/ModCard";

function mod(over: Partial<Mod>): Mod {
  return {
    id: "local:5", name: "Some mod", description: "", author: "", category: "", tags: [], downloads: 0,
    rating: 0, images: [], version: "", lastUpdated: "", backendModId: null, modKey: "local:5", ...over,
  };
}

const handlers = {
  onUninstall: vi.fn(), onUpdate: vi.fn(), onCheckUpdate: vi.fn(), onView: vi.fn(), onFavorite: vi.fn(),
  onOpenFilesTab: vi.fn(), onAssignModId: vi.fn(),
};

describe("InstalledModCard and subtitle mods", () => {
  for (const viewMode of ["grid", "list"] as const) {
    it(`does not ask for a mod id for a subtitle mod (${viewMode})`, () => {
      render(
        <InstalledModCard
          mod={mod({ name: "RU Subtitles Storm Voice", sourcePaths: ["RU Subtitles - Storm - Voice.zip"] })}
          viewMode={viewMode}
          {...handlers}
        />,
      );
      expect(screen.getAllByText("RU Subtitles Storm Voice").length).toBeGreaterThan(0); // the card is drawn
      expect(screen.queryByText(/Assign Mod ID/)).toBeNull();
      expect(screen.queryByText("Assign Author")).toBeNull();
    });

    it(`still asks for one for any other unlinked mod (${viewMode})`, () => {
      render(<InstalledModCard mod={mod({ sourcePaths: ["StormVoice.zip"] })} viewMode={viewMode} {...handlers} />);
      expect(screen.getByText(/Assign Mod ID/)).toBeInTheDocument();
    });
  }

  it("says who made it", () => {
    render(
      <InstalledModCard
        mod={mod({ sourcePaths: ["RU Subtitles - Storm - Voice.zip"] })}
        viewMode="grid"
        {...handlers}
      />,
    );
    expect(screen.getByText("Made by Voice Subtitles")).toBeInTheDocument();
  });
});
