/**
 * Progress rendering for "Rebuild Local Downloads".
 *
 * The step is driven entirely by parsing the script's log, so the parser has to
 * agree with what the script actually prints. It stopped agreeing when
 * migration 0022 added fingerprint-based skipping: a run that re-extracts only
 * the changed archives finishes having "processed" 2 of 213, and the parser
 * treated anything short of the total as still in flight. The user watched a
 * spinner on a task that had exited successfully fourteen minutes earlier.
 */
import { describe, expect, it } from "vitest";

import { summarizeTaskOutput } from "../logSummary";

/** The shape real runs produce, minus the per-archive noise. */
function ingestLog(opts: {
  total: number;
  extracted: number;
  skipped?: number;
  finished?: boolean;
}): string {
  const lines = [
    `2026-08-26 15:42:01 [INFO] Found ${opts.total} download row(s) to process`,
  ];
  if (opts.skipped) {
    lines.push(
      `2026-08-26 15:42:01 [INFO] Skipping ${opts.skipped} unchanged download(s); pass --force to re-ingest them.`,
    );
  }
  lines.push(`2026-08-26 15:42:01 [INFO] Extracting ${opts.extracted} download(s)`);
  for (let i = 0; i < opts.extracted; i += 1) {
    lines.push(
      `2026-08-26 15:42:02 [INFO] [Mod${i}] Extracting archive -> C:\\downloads\\Mod${i}.zip`,
    );
  }
  if (opts.finished !== false) {
    lines.push(
      `2026-08-26 15:42:07 [INFO] Processed ${opts.extracted} archive(s); wrote 5 pak(s) and 120 pak_assets.`,
    );
  }
  return lines.join("\n");
}

const step = (raw: string) => {
  const summary = summarizeTaskOutput("ingest_download_assets", raw);
  expect(summary.supported).toBe(true);
  return summary.steps[0];
};

describe("Rebuild Local Downloads progress", () => {
  it("a finished run that skipped unchanged archives is done, not active", () => {
    // The exact numbers the user reported: 213 downloads, 2 needed work.
    const s = step(ingestLog({ total: 213, extracted: 2, skipped: 211 }));
    expect(s.status).toBe("done");
    expect(s.label).toBe("Extracted mods");
  });

  it("the bar fills, rather than sitting at 2 of 213", () => {
    const s = step(ingestLog({ total: 213, extracted: 2, skipped: 211 }));
    expect(s.current).toBe(213);
    expect(s.total).toBe(213);
  });

  it("says why the extracted count is lower than the total", () => {
    // "Processed 2 of 213" reads like a stall. Naming the skipped archives is
    // the difference between a bug report and an explanation.
    const s = step(ingestLog({ total: 213, extracted: 2, skipped: 211 }));
    expect(s.detail).toBe("Extracted 2 of 213; 211 already up to date");
  });

  it("handles a run where nothing at all had changed", () => {
    const s = step(ingestLog({ total: 213, extracted: 0, skipped: 213 }));
    expect(s.status).toBe("done");
    expect(s.detail).toBe("All 213 archive(s) already up to date");
  });

  it("a first run with no skips still reports normally", () => {
    const s = step(ingestLog({ total: 3, extracted: 3 }));
    expect(s.status).toBe("done");
    expect(s.detail).toBe("Processed 3 of 3 archive(s)");
  });

  it("is still active while the run is genuinely in progress", () => {
    // No completion line yet: the step must keep spinning.
    const s = step(ingestLog({ total: 213, extracted: 2, skipped: 100, finished: false }));
    expect(s.status).toBe("active");
    expect(s.label).toBe("Extracting mods");
  });

  it("a completion line ends the step even when the totals disagree", () => {
    // Downloads that vanished from disk are counted in the total but never
    // extracted and never skipped, so the two numbers legitimately differ.
    const raw = [
      "[INFO] Found 10 download row(s) to process",
      "[INFO] Extracting 1 download(s)",
      "[INFO] [Mod0] Extracting archive -> C:\\downloads\\Mod0.zip",
      "[INFO] Processed 1 archive(s); wrote 2 pak(s) and 9 pak_assets.",
    ].join("\n");
    expect(step(raw).status).toBe("done");
  });

  it("does not mistake a failure summary for skipped archives", () => {
    // "Skipped N problematic download(s)" is a different line with a different
    // meaning; counting it as up-to-date would hide failures behind a full bar.
    const raw = [
      "[INFO] Found 5 download row(s) to process",
      "[INFO] Extracting 5 download(s)",
      "[WARNING] Skipped 3 problematic download(s): A, B, C",
      "[INFO] Processed 2 archive(s); wrote 2 pak(s) and 9 pak_assets.",
    ].join("\n");
    const s = step(raw);
    expect(s.detail).toBe("Processed 2 of 5 archive(s)");
  });
});
