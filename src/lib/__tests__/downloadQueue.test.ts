/**
 * Only a couple of downloads run at once; the rest wait and can be cancelled.
 *
 * Every pending download used to start the moment it was seen. Each is a
 * request held open for the whole transfer, and the webview allows six
 * connections to one host — so with six or more, every other call to the
 * backend queued behind them, including the progress polls and Cancel. From
 * the outside that was "a pile of downloads, none moving, and I cannot cancel".
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  MAX_CONCURRENT_DOWNLOADS,
  isAlreadyDownloading,
  planDownloads,
  queueSummary,
} from "../downloadQueue";

const pending = (n: number) =>
  Array.from({ length: n }, (_, i) => ({ id: `h${i}`, created_at: 100 + i }));

describe("planDownloads", () => {
  it("starts no more than the limit", () => {
    const plan = planDownloads(pending(10), 0);
    expect(plan.start).toHaveLength(MAX_CONCURRENT_DOWNLOADS);
    expect(plan.wait).toHaveLength(10 - MAX_CONCURRENT_DOWNLOADS);
  });

  it("stays under the webview's six connections per host", () => {
    // Leaves room for the progress polls and the Cancel request.
    expect(MAX_CONCURRENT_DOWNLOADS).toBeLessThanOrEqual(3);
  });

  it("counts what is already running", () => {
    const plan = planDownloads(pending(5), 1, 2);
    expect(plan.start).toHaveLength(1);
    expect(plan.wait).toHaveLength(4);
  });

  it("starts nothing when every slot is taken", () => {
    const plan = planDownloads(pending(3), 2, 2);
    expect(plan.start).toEqual([]);
    expect(plan.wait).toHaveLength(3);
  });

  it("is first come, first served", () => {
    // The backend lists newest first; the queue must not serve it that way.
    const newestFirst = pending(4).reverse();
    const plan = planDownloads(newestFirst, 0, 2);
    expect(plan.start.map((h) => h.id)).toEqual(["h0", "h1"]);
    expect(plan.wait.map((h) => h.id)).toEqual(["h2", "h3"]);
  });

  it("does not reorder the caller's array", () => {
    const list = pending(3).reverse();
    const before = list.map((h) => h.id);
    planDownloads(list, 0);
    expect(list.map((h) => h.id)).toEqual(before);
  });

  it("copes with an over-full count", () => {
    expect(planDownloads(pending(2), 9, 2).start).toEqual([]);
  });

  it("treats a missing timestamp as oldest", () => {
    const plan = planDownloads(
      [
        { id: "dated", created_at: 50 },
        { id: "undated", created_at: null },
      ],
      0,
      1,
    );
    expect(plan.start[0].id).toBe("undated");
  });
});

describe("isAlreadyDownloading", () => {
  it("recognises the backend's refusal", () => {
    const err = Object.assign(new Error("This file is already being downloaded"), {
      status: 409,
      body: { detail: { message: "…", in_progress: true } },
    });
    expect(isAlreadyDownloading(err)).toBe(true);
  });

  it("does not mistake a finished duplicate for it", () => {
    const err = Object.assign(new Error("already exists"), {
      status: 409,
      body: { detail: { message: "already exists" } },
    });
    expect(isAlreadyDownloading(err)).toBe(false);
  });

  it("is safe on anything else", () => {
    expect(isAlreadyDownloading(null)).toBe(false);
    expect(isAlreadyDownloading("nope")).toBe(false);
    expect(isAlreadyDownloading(new Error("x"))).toBe(false);
    expect(isAlreadyDownloading({ body: "text" })).toBe(false);
  });
});

describe("queueSummary", () => {
  it("counts in plain words", () => {
    expect(queueSummary(1)).toBe("1 download queued");
    expect(queueSummary(5)).toBe("5 downloads queued");
  });
});

describe("the listener uses the queue", () => {
  const source = readFileSync(
    join(__dirname, "..", "..", "components", "NxmBackgroundListener.tsx"),
    "utf8",
  );

  it("plans before it starts anything", () => {
    expect(source).toContain("planDownloads(eligible, processingRef.current.size)");
  });

  it("no longer starts every pending handoff from inside the scan loop", () => {
    const loop = source.slice(
      source.indexOf("for (const handoff of handoffs)"),
      source.indexOf("const plan = planDownloads"),
    );
    expect(loop).not.toContain("void processHandoff(handoff)");
  });

  it("offers a way to cancel what is waiting", () => {
    expect(source).toContain("Cancel queued");
  });

  it("does not dismiss a handoff that is mid-download elsewhere", () => {
    const branch = source.slice(
      source.indexOf("if (isAlreadyDownloading(err))"),
      source.indexOf("// Treat 404 (Not Found / Expired)"),
    );
    expect(branch).not.toContain("dismissNxmHandoff");
  });
});
