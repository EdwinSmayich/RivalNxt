import { Copy, FolderOpen, Share2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { revealVoiceFile, type VoiceMod, type VoiceSubtitleState } from "../lib/api";

function PathRow({ path, onShow }: { path: string; onShow: () => void }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(path);
      toast.success("Path copied");
    } catch {
      toast.error("Could not copy the path");
    }
  };
  return (
    <div className="space-y-2">
      <div className="rounded-md border bg-muted/40 px-3 py-2 font-mono text-xs break-all" title={path}>
        {path}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={onShow}>
          <FolderOpen className="h-4 w-4" /> Show in folder
        </Button>
        <Button size="sm" variant="ghost" onClick={copy}>
          <Copy className="h-4 w-4" /> Copy path
        </Button>
      </div>
    </div>
  );
}

/** Where a voice mod's subtitles are kept, and how to pass them on. */
export function VoiceFilesDialog({
  mod,
  language,
  languageName,
  subtitles,
  onClose,
}: {
  mod: VoiceMod;
  language: string;
  languageName: string;
  subtitles: VoiceSubtitleState;
  onClose: () => void;
}) {
  const show = async (what: "subtitle-mod" | "translations") => {
    try {
      await revealVoiceFile(mod.key, language, what);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="pr-6 break-words">
            {mod.hero_name} · {mod.name.replace(/_\d+_P\.pak$/i, "")}
          </DialogTitle>
          <DialogDescription>Where these {languageName} subtitles are kept, and how to share them.</DialogDescription>
        </DialogHeader>

        <section className="space-y-2">
          <h4 className="text-sm font-medium flex items-center gap-2">
            <Share2 className="h-4 w-4" /> The subtitle mod — the file to share
          </h4>
          <p className="text-sm text-muted-foreground">
            This one file holds every subtitle line{subtitles.shared ? "" : ", your corrections included"}. Someone
            with the same voice mod adds it to RivalNxt with <span className="font-medium">Add Mods</span> and switches
            it on beside the voice mod; they need no speech recognition or translation model for it.
          </p>
          {subtitles.archive_path ? (
            <PathRow path={subtitles.archive_path} onShow={() => show("subtitle-mod")} />
          ) : (
            <p className="text-sm text-amber-500">Not made yet.</p>
          )}
        </section>

        {subtitles.shared ? (
          <p className="text-sm text-muted-foreground">
            Made on another computer: it carries the finished lines only, so there is nothing here to review or
            translate again.
          </p>
        ) : (
          <section className="space-y-2">
            <h4 className="text-sm font-medium flex items-center gap-2">
              <FolderOpen className="h-4 w-4" /> What was heard, the translations and your corrections
            </h4>
            <p className="text-sm text-muted-foreground">
              Kept so the subtitle mod can be made again — with a better model, or after a game update. They belong to
              this voice mod only; to share subtitles, share the file above.
            </p>
            <PathRow path={mod.work_path} onShow={() => show("translations")} />
          </section>
        )}
      </DialogContent>
    </Dialog>
  );
}
