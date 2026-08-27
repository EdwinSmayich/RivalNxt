/**
 * The one-liner behind "Copy helper".
 *
 * It exists because the app cannot read a mod's gallery itself: neither Nexus
 * API exposes a per-mod image list, and the mod page answers automated requests
 * with a Cloudflare challenge. So the user's own browser does the reading, on a
 * page they already have open, and pastes the result back.
 *
 * It ships as a string and runs somewhere this project cannot reach, which is
 * exactly why it is worth testing: a typo in it fails silently in someone
 * else's console with no way for them to tell what went wrong.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** Pull the literal out of the component rather than restating it here. */
function loadSnippet(): string {
  const source = readFileSync(
    resolve(__dirname, "../../components/ModModal.tsx"),
    "utf8",
  );
  const start = source.indexOf("const GALLERY_URL_SNIPPET =");
  expect(start).toBeGreaterThan(-1);
  const end = source.indexOf('";', start);
  const literal = source.slice(
    start + "const GALLERY_URL_SNIPPET =".length,
    end + 1,
  );
  // eslint-disable-next-line no-eval
  return eval(literal) as string;
}

const FULL =
  "https://staticdelivery.nexusmods.com/mods/7106/images/5070/5070-1764476821-126078100.png";
const SECOND =
  "https://staticdelivery.nexusmods.com/mods/7106/images/5070/5070-1764476877-897252227.png";
const THUMB =
  "https://staticdelivery.nexusmods.com/mods/7106/images/thumbnails/5070/5070-1764476877-897252227.png";
/** Community uploads live under a different path and belong to no mod. */
const COMMUNITY =
  "https://staticdelivery.nexusmods.com/images/7106/191886936-1787793869.png";
const MOD_PAGE = "https://www.nexusmods.com/marvelrivals/mods/5070";

/** Run the snippet against a fake page and return what it put on the clipboard. */
function run(elements: Record<string, unknown>[]): string[] {
  const snippet = loadSnippet();
  let copied = "";
  const scope = {
    document: { querySelectorAll: () => elements },
    copy: (value: string) => {
      copied = value;
    },
  };
  // eslint-disable-next-line no-new-func
  new Function("document", "copy", snippet)(scope.document, scope.copy);
  return copied ? copied.split("\n") : [];
}

describe("gallery URL snippet", () => {
  it("collects a mod's image addresses", () => {
    expect(run([{ src: FULL }])).toEqual([FULL]);
  });

  it("rewrites thumbnails to their full-size path", () => {
    // The grid shows thumbnails; importing those would store postage stamps.
    expect(run([{ src: THUMB }])).toEqual([SECOND]);
  });

  it("drops the duplicate each image appears as", () => {
    // Every picture is on the page twice: the thumbnail and the link behind it.
    expect(run([{ src: THUMB }, { href: SECOND }])).toEqual([SECOND]);
  });

  it("strips query strings", () => {
    expect(run([{ href: `${FULL}?tab=images` }])).toEqual([FULL]);
  });

  it("reads lazy-loaded images too", () => {
    expect(run([{ dataset: { src: FULL } }])).toEqual([FULL]);
  });

  it("ignores community uploads, which belong to no mod", () => {
    expect(run([{ src: COMMUNITY }])).toEqual([]);
  });

  it("ignores links that are not images", () => {
    expect(run([{ href: MOD_PAGE }])).toEqual([]);
  });

  it("survives elements with no usable attribute", () => {
    expect(run([{}, { src: null }, { href: undefined }, { src: FULL }])).toEqual([
      FULL,
    ]);
  });

  it("keeps every distinct image of the mod", () => {
    const result = run([{ src: FULL }, { src: THUMB }, { src: COMMUNITY }]);
    expect(result).toHaveLength(2);
    expect(result).toContain(FULL);
    expect(result).toContain(SECOND);
  });
});
