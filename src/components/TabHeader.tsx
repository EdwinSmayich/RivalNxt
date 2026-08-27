import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Settings, RefreshCw, Rocket, Play, Archive, PowerOff, ShieldAlert, RotateCcw, Bookmark, Globe, History } from "lucide-react";
import { open } from "@tauri-apps/plugin-shell";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "./ui/alert-dialog";

interface TabHeaderProps {
  activeTab: "downloads" | "active" | "collections" | "nexus";
  onTabChange: (tab: "downloads" | "active" | "collections" | "nexus") => void;
  downloadsCount: number;
  activeCount: number;
  collectionsCount?: number;

  onRefresh?: () => void;
  onOpenSettings?: () => void;
  onOpenBootstrap?: () => void;
  onOpenBackup?: () => void;
  onOpenActivity?: () => void;
  onDisableAllMods?: () => void;
  /** Re-applies the loadout remembered by the last Disable All. */
  onRestoreLoadout?: () => void;
  /** Summary of that loadout, or null when nothing is remembered. */
  rememberedLoadout?: { activeDownloads: number; activePaks: number; createdAt: string } | null;
  /** Saved named presets, offered in a dropdown next to Disable All. */
  presets?: { id: string; name: string; activeDownloads: number; activePaks: number }[];
  onApplyPreset?: (presetId: string) => void;
  /** Preset matching what is enabled right now, so the user can see it. */
  activePresetId?: string | null;
  /** Called when the user clicks "Last Crash" to re-open the crash modal */
  onViewLastCrash?: () => void;
  /** Whether there is a crash available to view */
  hasLastCrash?: boolean;
}

export function TabHeader({
  activeTab,
  onTabChange,
  downloadsCount,
  activeCount,
  collectionsCount = 0,

  onRefresh,
  onOpenSettings,
  onOpenBootstrap,
  onOpenBackup,
  onOpenActivity,
  onDisableAllMods,
  onRestoreLoadout,
  rememberedLoadout = null,
  presets = [],
  onApplyPreset,
  activePresetId = null,
  onViewLastCrash,
  hasLastCrash = false,
}: TabHeaderProps) {
  return (
    <div className="border-b border-border bg-card" style={{ contain: 'layout paint' }}>
      {/* Wraps instead of overflowing: on a small window the action row moves
          onto a second line rather than being pushed out of sight, which is why
          the window previously had to be maximised to be usable. */}
      <div className="flex items-center gap-3 p-4 justify-between flex-wrap">
        <div className="flex gap-1 flex-wrap min-w-0">
          <Button
            variant={activeTab === "downloads" ? "secondary" : "ghost"}
            onClick={() => onTabChange("downloads")}
            className="gap-2"
          >
            Downloads
            <Badge variant="secondary" className="text-xs">
              {downloadsCount}
            </Badge>
          </Button>

          <Button
            variant={activeTab === "active" ? "secondary" : "ghost"}
            onClick={() => onTabChange("active")}
            className="gap-2"
          >
            Active Mods
            <Badge variant="secondary" className="text-xs">
              {activeCount}
            </Badge>
          </Button>

          <Button
            variant={activeTab === "collections" ? "secondary" : "ghost"}
            onClick={() => onTabChange("collections")}
            className="gap-2"
          >
            Collections
            <Badge variant="secondary" className="text-xs">
              {collectionsCount}
            </Badge>
          </Button>

          <Button
            variant={activeTab === "nexus" ? "secondary" : "ghost"}
            onClick={() => onTabChange("nexus")}
            className="gap-2"
          >
            <Globe className="w-4 h-4 shrink-0" />
            Browse Nexus
          </Button>
        </div>

        <div className="flex items-center gap-3 flex-wrap">

          <div className="flex items-center gap-2 flex-wrap">

            {hasLastCrash && onViewLastCrash && (
              <Button
                variant="outline"
                size="sm"
                onClick={onViewLastCrash}
                className="header-action-btn"
                style={{
                  borderColor: "rgba(234,88,12,0.6)",
                  color: "#fb923c",
                  animation: "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
                }}
                title="View last crash report"
              >
                <ShieldAlert className="w-4 h-4 shrink-0" />
                <span className="header-action-text">Last Crash</span>
              </Button>
            )}
            {onOpenBootstrap && (
              <Button
                variant="outline"
                size="sm"
                onClick={onOpenBootstrap}
                className="header-action-btn"
                title="Setup"
              >
                <Rocket className="w-4 h-4 shrink-0" />
                <span className="header-action-text">
                  Setup
                </span>
              </Button>
            )}
            {onOpenBackup && (
              <Button
                variant="outline"
                size="sm"
                onClick={onOpenBackup}
                className="header-action-btn"
                title="Backup"
              >
                <Archive className="w-4 h-4 shrink-0" />
                <span className="header-action-text">
                  Backup
                </span>
              </Button>
            )}
            {onOpenActivity && (
              <Button
                variant="outline"
                size="sm"
                onClick={onOpenActivity}
                className="header-action-btn"
                title="History — what this app changed"
              >
                <History className="w-4 h-4 shrink-0" />
                <span className="header-action-text">History</span>
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => open('steam://rungameid/2767030')}
              className="header-action-btn"
              title="Start Game"
            >
              <Play className="w-4 h-4 shrink-0" />
              <span className="header-action-text">
                Start Game
              </span>
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onRefresh}
              className="header-action-btn"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4 shrink-0" />
              <span className="header-action-text">
                Refresh
              </span>
            </Button>

            {onDisableAllMods && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="destructive"
                    size="sm"
                    className="header-action-btn"
                    title="Disable All Mods"
                  >
                    <PowerOff className="w-4 h-4 shrink-0" />
                    <span className="header-action-text">
                      Disable All
                    </span>
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Disable All Mods</AlertDialogTitle>
                    <AlertDialogDescription>
                      Your current loadout is saved first, so you can put it back
                      with <strong>Restore Loadout</strong> — including which pak
                      variant each mod had enabled. Mod artwork and tags are not
                      touched; only the .pak files leave the game folder.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={onDisableAllMods}>
                      Disable All
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}

            {/* A native select rather than the Radix dropdown used elsewhere.
                This header is in the eager startup bundle, and pulling
                @radix-ui/react-dropdown-menu into it pushed startup bytes over
                budget — the component is otherwise only reached through the
                lazily-loaded SearchHeader. */}
            {/* Presets open a dialog rather than a dropdown. This header is in
                the eager startup bundle, and both Radix Select and DropdownMenu
                push it past its size budget — measured, twice. AlertDialog is
                already here for Disable All, so it costs nothing, and unlike a
                native select Windows does not draw it as a white panel with
                unreadable text over the dark UI. */}
            {onApplyPreset && presets.length > 0 && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className="header-action-btn"
                    style={{
                      borderColor: "rgba(168,85,247,0.5)",
                      color: "#a855f7",
                      fontWeight: activePresetId ? 600 : 400,
                    }}
                    title={
                      activePresetId
                        ? `Preset "${presets.find((p) => p.id === activePresetId)?.name}" is loaded`
                        : "Apply a saved preset"
                    }
                  >
                    <Bookmark
                      className="w-4 h-4 shrink-0"
                      fill={activePresetId ? "currentColor" : "none"}
                    />
                    <span className="header-action-text">
                      {presets.find((p) => p.id === activePresetId)?.name ?? "Presets"}
                    </span>
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Presets</AlertDialogTitle>
                    <AlertDialogDescription>
                      {activePresetId
                        ? "The highlighted preset is loaded right now."
                        : "None of your presets matches what is enabled right now."}
                    </AlertDialogDescription>
                  </AlertDialogHeader>

                  <div className="flex flex-col gap-2 py-2 max-h-72 overflow-y-auto">
                    {presets.map((preset) => {
                      const loaded = preset.id === activePresetId;
                      return (
                        <div
                          key={preset.id}
                          className="flex items-center gap-3 rounded-lg border px-3 py-2"
                          style={{
                            borderColor: loaded
                              ? "rgba(168,85,247,0.55)"
                              : "hsl(var(--border))",
                            background: loaded ? "rgba(168,85,247,0.12)" : "transparent",
                          }}
                        >
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium truncate">{preset.name}</p>
                            <p className="text-xs text-muted-foreground">
                              {preset.activeDownloads} mods · {preset.activePaks} paks
                            </p>
                          </div>
                          {loaded ? (
                            <Badge
                              className="text-xs shrink-0"
                              style={{ background: "#a855f7", color: "white" }}
                            >
                              Loaded
                            </Badge>
                          ) : (
                            <AlertDialogAction
                              onClick={() => onApplyPreset(preset.id)}
                              className="h-8 px-3 text-xs shrink-0"
                            >
                              Apply
                            </AlertDialogAction>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  <AlertDialogFooter>
                    <AlertDialogCancel>Close</AlertDialogCancel>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}

            {onRestoreLoadout && rememberedLoadout && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className="header-action-btn"
                    style={{ borderColor: "rgba(56,189,248,0.5)", color: "#38bdf8" }}
                    title={`${rememberedLoadout.activeDownloads} mods remembered`}
                  >
                    <RotateCcw className="w-4 h-4 shrink-0" />
                    <span className="header-action-text">Restore Loadout</span>
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Restore Loadout</AlertDialogTitle>
                    <AlertDialogDescription>
                      Re-enables the {rememberedLoadout.activeDownloads} mod
                      {rememberedLoadout.activeDownloads === 1 ? "" : "s"} (
                      {rememberedLoadout.activePaks} pak file
                      {rememberedLoadout.activePaks === 1 ? "" : "s"}) that were
                      active before the last Disable All, saved{" "}
                      {new Date(rememberedLoadout.createdAt).toLocaleString()}.
                      Anything enabled since then that is not in the loadout will
                      be switched off.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={onRestoreLoadout}>
                      Restore
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={onOpenSettings}
            >
              <Settings className="w-4 h-4 shrink-0" />
              Settings
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
