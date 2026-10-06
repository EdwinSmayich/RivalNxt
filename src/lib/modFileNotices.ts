/**
 * What the backend says about files it could not deal with.
 *
 * Switching a mod off while the game is running removes its .pak — the mod is
 * off — but the game keeps the mod's container open, and Windows will not
 * delete an open file. The backend used to say nothing about that. It now
 * answers with a `warning`, and this is the one place that shows it: there are
 * twenty call sites that switch mods on and off, and a notice each of them had
 * to remember to show is a notice most of them would not.
 */
import { toast } from "sonner";

/** One toast, however many mods a batch switched off. */
export const MOD_FILE_NOTICE_TOAST_ID = "mod-files-in-use";

/** The warning carried by an activation response, or null if there is none. */
export function warningFrom(result: unknown): string | null {
  if (!result || typeof result !== "object") return null;
  const warning = (result as Record<string, unknown>).warning;
  if (typeof warning !== "string") return null;
  const text = warning.trim();
  return text.length > 0 ? text : null;
}

/** Show the warning in `result`, if it has one. Returns whether it did. */
export function showModFileWarning(result: unknown): boolean {
  const text = warningFrom(result);
  if (!text) return false;
  toast.warning("Some files are still in use", {
    id: MOD_FILE_NOTICE_TOAST_ID,
    description: text,
    duration: 12_000,
  });
  return true;
}
