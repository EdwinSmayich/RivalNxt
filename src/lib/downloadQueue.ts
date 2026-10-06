/**
 * Which pending downloads start now, and which wait.
 *
 * Every pending download used to start the moment it was seen. Each one is a
 * request that stays open for the whole transfer, and the webview allows six
 * connections to one host — so with six or more downloads running, every other
 * call to the backend queued behind them, including the progress polls and the
 * Cancel button. That is what "a pile of downloads, none of them moving, and I
 * cannot cancel" was. A bandwidth-capped Nexus account made it worse: the same
 * speed divided between all of them.
 *
 * Kept as a pure function so the decision can be tested without a webview.
 */

/** Comfortably under the webview's six-connections-per-host limit. */
export const MAX_CONCURRENT_DOWNLOADS = 2;

/** How often a waiting download is re-announced so the backend keeps it. */
export const QUEUE_KEEPALIVE_MS = 60_000;

export interface QueueCandidate {
  id: string;
  created_at?: number | null;
}

export interface DownloadPlan<T> {
  start: T[];
  wait: T[];
}

/**
 * Split `eligible` into what may start and what must wait, oldest first.
 *
 * `activeCount` is how many transfers are already running.
 */
export function planDownloads<T extends QueueCandidate>(
  eligible: readonly T[],
  activeCount: number,
  limit: number = MAX_CONCURRENT_DOWNLOADS,
): DownloadPlan<T> {
  const ordered = [...eligible].sort(
    (a, b) => (a.created_at ?? 0) - (b.created_at ?? 0),
  );
  const free = Math.max(0, limit - Math.max(0, activeCount));
  return { start: ordered.slice(0, free), wait: ordered.slice(free) };
}

/** True when the backend refused because this very file is mid-download. */
export function isAlreadyDownloading(err: unknown): boolean {
  if (typeof err !== "object" || err === null) return false;
  const body = (err as { body?: unknown }).body;
  if (typeof body !== "object" || body === null) return false;
  const detail = (body as { detail?: unknown }).detail;
  return (
    typeof detail === "object" &&
    detail !== null &&
    (detail as { in_progress?: unknown }).in_progress === true
  );
}

/**
 * What "Cancel queued" should cancel at the moment it is clicked.
 *
 * The button lives in a toast that is only redrawn when the *number* waiting
 * changes. One download starting while another arrives leaves the number as it
 * was, so a list captured when the toast was drawn went stale: the click then
 * cancelled a download that had since started, and missed the newcomer. The
 * list is read at click time instead, and anything already running is left
 * alone.
 */
export function stillWaiting<T extends { id: string }>(
  latest: readonly T[],
  running: ReadonlySet<string>,
): T[] {
  return latest.filter((handoff) => !running.has(handoff.id));
}

/** "3 downloads queued" / "1 download queued". */
export function queueSummary(waiting: number): string {
  return `${waiting} download${waiting === 1 ? "" : "s"} queued`;
}
