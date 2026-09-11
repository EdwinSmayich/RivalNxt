import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getGamePatchStatus, type GamePatchStatus } from "@/lib/api";

/**
 * When the game last changed, and which mods have moved since.
 *
 * A game patch can break every installed mod at once. When that happened the
 * only way to find out which authors had posted anything since was to open all
 * 167 cards in turn — the answer was already in the database, just never asked
 * for.
 *
 * "Updated since the patch" is deliberately not called "fixed": an author may
 * have changed a screenshot. It narrows the list to what is worth re-checking.
 */
export function GamePatchPanel() {
  const [status, setStatus] = useState<GamePatchStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStatus(await getGamePatchStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const when = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });

  return (
    <div className="rounded-lg border border-border p-4">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">Game patch</h3>
          <p className="text-sm text-muted-foreground">
            A patch can stop mods applying until their authors rebuild them.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void load()}
          disabled={loading}
          aria-label="Re-check"
        >
          <RefreshCw className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        </Button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {status?.known === false && (
        <p className="text-sm text-muted-foreground">{status.reason}</p>
      )}

      {status?.known === true && (
        <>
          <p className="text-sm">
            Last patched <strong>{when(status.patched_at)}</strong>
          </p>
          <p className="mb-3 text-xs text-muted-foreground">
            read from {status.detected_from}
          </p>

          <p className="text-sm">
            <strong>{status.updated_count}</strong> of {status.mods_total} mods
            updated since
          </p>

          {status.updated_count === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">
              No author has posted anything yet. Nothing to do but wait.
            </p>
          ) : (
            <ul className="mt-3 flex flex-col gap-2">
              {status.updated.slice(0, 12).map((mod) => (
                <li key={mod.mod_id} className="text-sm">
                  <a
                    href={`https://www.nexusmods.com/marvelrivals/mods/${mod.mod_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium hover:underline"
                  >
                    {mod.name ?? `Mod ${mod.mod_id}`}
                  </a>
                  <span className="text-muted-foreground">
                    {" — "}
                    {when(mod.updated_at)}
                    {mod.author ? ` · ${mod.author}` : ""}
                  </span>
                </li>
              ))}
              {status.updated.length > 12 && (
                <li className="text-xs text-muted-foreground">
                  and {status.updated.length - 12} more
                </li>
              )}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

export default GamePatchPanel;
