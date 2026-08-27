import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp, Check, Loader2, Circle } from "lucide-react";

import type { SettingsTask } from "../lib/api";
import { summarizeTaskOutput } from "../lib/logSummary";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";
import { cn } from "./ui/utils";

interface TaskOutputSummaryProps {
  task?: SettingsTask;
  output: string;
  isRunning?: boolean;
  fallbackMinHeight?: string;
  showRawToggle?: boolean;
  style?: React.CSSProperties;
  /** ISO timestamp the run started, used only to estimate what is left. */
  startedAt?: string | null;
}

/**
 * Steps summarizeBootstrap can emit, in order.
 *
 * A fixed denominator matters: the step list only grows as the log reveals each
 * stage, so measuring progress against the steps seen *so far* would sit at
 * 100% from the first line and lurch backwards as new ones appeared.
 */
const BOOTSTRAP_STEP_IDS = [
  "database",
  "ue_extraction",
  "downloads",
  "sync",
  "extract",
  "tags",
  "conflicts",
] as const;

/**
 * Fraction of the whole task that is done, 0..1, or null when unknowable.
 *
 * A step counts as its own completion fraction when it reports counts, so the
 * long extraction stage moves the bar rather than jumping from 0 to 1.
 */
function computeProgress(
  steps: { id: string; status: string; current?: number; total?: number }[],
  task?: SettingsTask,
): number | null {
  if (steps.length === 0) return null;

  const denominator =
    task === "bootstrap_rebuild" || steps.some((s) => s.id === "ue_extraction")
      ? BOOTSTRAP_STEP_IDS.length
      : steps.length;

  let completed = 0;
  for (const step of steps) {
    if (step.status === "done") {
      completed += 1;
    } else if (step.status === "active") {
      const { current, total } = step;
      if (typeof current === "number" && typeof total === "number" && total > 0) {
        completed += Math.min(current / total, 1);
      } else {
        // In flight with nothing to measure by. Half is the least wrong guess.
        completed += 0.5;
      }
    }
  }
  return Math.max(0, Math.min(completed / denominator, 1));
}

/** "about 2 min left" — deliberately vague, because it is a linear guess. */
function formatRemaining(elapsedMs: number, fraction: number): string | null {
  // Below a few percent the extrapolation is noise; above 99.5% it reads as
  // stuck. Neither is worth showing.
  if (fraction <= 0.03 || fraction >= 0.995) return null;
  const totalMs = elapsedMs / fraction;
  const remaining = Math.max(0, totalMs - elapsedMs);
  if (remaining < 10_000) return "a few seconds left";
  if (remaining < 90_000) return `about ${Math.round(remaining / 10_000) * 10}s left`;
  const minutes = Math.round(remaining / 60_000);
  return `about ${minutes} min left`;
}

export function TaskOutputSummary({
  task,
  output,
  isRunning = false,
  fallbackMinHeight = "h-40",
  showRawToggle = true,
  style,
  startedAt,
}: TaskOutputSummaryProps) {
  const trimmed = output?.trim() ?? "";
  const [showRaw, setShowRaw] = useState(false);

  // Ticks only while running, and only so the estimate ages between log lines.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isRunning) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [isRunning]);

  const summary = useMemo(() => {
    // Try primary task first, then fall back to other known task types when
    // the primary parser doesn't recognize the log. This helps when a
    // wrapper task (like bootstrap_rebuild) streams logs from subtasks
    // such as ingest_download_assets — ensure we still detect progress.
    const primary = summarizeTaskOutput(task, trimmed);
    if (primary.supported) return primary;

    const candidates: (SettingsTask | undefined)[] = [
      "ingest_download_assets",
      "bootstrap_rebuild",
      "rebuild_conflicts",
      "rebuild_tags",
      "sync_nexus",
      undefined,
    ];

    for (const cand of candidates) {
      if (cand === task) continue;
      const s = summarizeTaskOutput(cand, trimmed);
      if (s.supported) return s;
    }

    return primary;
  }, [task, trimmed]);

  if (!trimmed) {
    return (
      <div
        className={cn(
          "rounded-md border border-dashed border-border/40 bg-muted/5 p-4 text-sm text-muted-foreground",
          fallbackMinHeight
        )}
        style={style}
      >
        {isRunning ? "Waiting for output…" : "No output captured."}
      </div>
    );
  }

  if (!summary.supported || summary.steps.length === 0) {
    return (
      <Textarea
        readOnly
        className={cn("resize-y font-mono text-xs", fallbackMinHeight)}
        style={style}
        value={trimmed}
        spellCheck={false}
      />
    );
  }

  const progressRows = summary.steps.map((step) => {
    const statusClass =
      step.status === "done"
        ? "text-emerald-500"
        : step.status === "active"
        ? "text-primary"
        : "text-muted-foreground";

    const total =
      typeof step.total === "number" && step.total > 0 ? step.total : undefined;

    let current =
      typeof step.current === "number" && step.current >= 0
        ? step.current
        : undefined;

    if (typeof current === "number" && typeof total === "number") {
      current = Math.min(current, total);
    } else if (
      typeof total === "number" &&
      current === undefined &&
      step.status === "done"
    ) {
      current = total;
    }

    const hasCurrent = typeof current === "number";
    const hasTotal = typeof total === "number";
    const showCounts = hasCurrent || hasTotal;
    let prefixText: string | undefined;
    if (showCounts) {
      if (hasCurrent && hasTotal) {
        prefixText = `(${current as number}/${total})`;
      } else if (hasCurrent) {
        prefixText = `(${current as number})`;
      } else if (hasTotal) {
        const fallbackCurrent = step.status === "done" ? total : 0;
        prefixText = `(${fallbackCurrent}/${total})`;
      }
    }

    const labelText = prefixText ? `${prefixText} ${step.label}` : step.label;

    let indicator: ReactNode;
    if (step.status === "done") {
      indicator = <Check className="h-4 w-4 text-emerald-500" aria-hidden />;
    } else if (step.status === "active") {
      indicator = (
        <Loader2
          className="h-3.5 w-3.5 animate-spin text-primary"
          aria-hidden
        />
      );
    } else {
      indicator = (
        <Circle className="h-3 w-3 text-muted-foreground" aria-hidden />
      );
    }

    return (
      <div
        key={step.id}
        className="flex flex-col gap-1 text-sm leading-relaxed"
      >
        <div className="flex items-center gap-2">
          {indicator}
          <span className={cn(statusClass, "tabular-nums")}>{labelText}</span>
        </div>
        {step.detail ? (
          <span className="ml-6 text-xs text-muted-foreground">
            {step.detail}
          </span>
        ) : null}
      </div>
    );
  });

  const fraction = computeProgress(summary.steps, task);
  const percent = fraction === null ? null : Math.round(fraction * 100);
  const startedMs = startedAt ? new Date(startedAt).getTime() : NaN;
  const remaining =
    isRunning && fraction !== null && Number.isFinite(startedMs)
      ? formatRemaining(Math.max(0, now - startedMs), fraction)
      : null;

  return (
    <div className="space-y-3" style={style}>
      <div className="rounded-lg border border-border/40 bg-muted/5 p-4">
        {/* "190/200 mods" said nothing about the checks still to run after it,
            so a run that was nearly over looked identical to one that was not. */}
        {percent !== null ? (
          <div className="mb-3">
            <div className="flex items-baseline justify-between gap-3 mb-1.5">
              <span className="text-sm font-medium tabular-nums">{percent}%</span>
              {remaining ? (
                <span className="text-xs text-muted-foreground">{remaining}</span>
              ) : null}
            </div>
            <div
              className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-valuenow={percent}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-500",
                  percent >= 100 ? "bg-emerald-500" : "bg-primary",
                )}
                style={{ width: `${percent}%` }}
              />
            </div>
          </div>
        ) : null}
        <div className="flex flex-col gap-2">{progressRows}</div>
      </div>

      {showRawToggle ? (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Raw log available for diagnostics.</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-xs"
            onClick={() => setShowRaw((prev) => !prev)}
          >
            {showRaw ? (
              <>
                <ChevronUp className="mr-1 h-3 w-3" /> Hide raw log
              </>
            ) : (
              <>
                <ChevronDown className="mr-1 h-3 w-3" /> Show raw log
              </>
            )}
          </Button>
        </div>
      ) : null}

      {showRawToggle && showRaw ? (
        <Textarea
          readOnly
          className={cn("resize-y font-mono text-xs", fallbackMinHeight)}
          style={style}
          value={trimmed}
          spellCheck={false}
        />
      ) : null}
    </div>
  );
}
