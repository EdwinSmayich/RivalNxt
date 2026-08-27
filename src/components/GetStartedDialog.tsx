import {
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type ChangeEvent,
} from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import {
  AlertCircle,
  CheckCircle,
  Hammer,
  Loader2,
  RotateCcw,
  Folder,
  ExternalLink,
  LogIn,
} from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { toast } from "sonner";
import type {
  ApiBootstrapStatus,
  ApiSettings,
  ApiSettingsTaskResponse,
} from "../lib/api";
import { validatePath } from "../lib/api";
import type { SettingsFormValues } from "./SettingsDialog";
import { TaskOutputSummary } from "./TaskOutputSummary";
import { initiateNexusSso, NEXUS_APPLICATION_SLUG } from "../lib/nexusSso";

const EMPTY_VALUES: SettingsFormValues = {
  data_dir: "",
  marvel_rivals_root: "",
  marvel_rivals_local_downloads_root: "",
  nexus_api_key: "",
  aes_key_hex: "",
  allow_direct_api_downloads: false,
  seven_zip_bin: "",
};

type Stage = "collect" | "ready" | "running" | "complete";
type WizardStep = 1 | 2 | 3;

interface GetStartedDialogProps {
  open: boolean;
  loadingSettings: boolean;
  savingSettings: boolean;
  settings: ApiSettings | null;
  bootstrapStatus: ApiBootstrapStatus | null;
  job: ApiSettingsTaskResponse | null;
  jobRunning: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: SettingsFormValues) => Promise<boolean>;
  onRunBootstrap: () => Promise<boolean>;
  onRefreshSettings: () => void;
  onRefreshStatus: () => void;
}

export function GetStartedDialog({
  open,
  loadingSettings,
  savingSettings,
  settings,
  bootstrapStatus,
  job,
  jobRunning,
  onOpenChange,
  onSubmit,
  onRunBootstrap,
  onRefreshSettings,
  onRefreshStatus,
}: GetStartedDialogProps) {
  const [formValues, setFormValues] =
    useState<SettingsFormValues>(EMPTY_VALUES);
  const [stage, setStage] = useState<Stage>("collect");
  const [wizardStep, setWizardStep] = useState<WizardStep>(1);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pathCheckResults, setPathCheckResults] = useState<
    Record<string, { ok: boolean; message: string }>
  >({});
  const [, setValidatingFields] = useState<Set<string>>(new Set());

  // Debounce timer refs for each field
  const debounceTimers = useState<Record<string, NodeJS.Timeout>>(
    () => ({}),
  )[0];

  // Nexus SSO state
  const [isNexusSsoLoading, setIsNexusSsoLoading] = useState(false);
  const [nexusSsoStatus, setNexusSsoStatus] = useState<{
    stage: "connecting" | "waiting" | "authorized" | "error";
    message: string;
  } | null>(null);

  useEffect(() => {
    if (!open) {
      return; // Don't reset when closing
    }
    if (settings) {
      // Always update form values when settings change
      setFormValues({
        data_dir: settings.data_dir ?? "",
        marvel_rivals_root: settings.marvel_rivals_root ?? "",
        marvel_rivals_local_downloads_root:
          settings.marvel_rivals_local_downloads_root ?? "",
        nexus_api_key: settings.nexus_api_key ?? "",
        aes_key_hex: settings.aes_key_hex ?? "",
        allow_direct_api_downloads: settings.allow_direct_api_downloads,
        seven_zip_bin: settings.seven_zip_bin ?? "",
      });

      // Auto-detect sidecars if not set
      const autoDetectSidecars = async () => {
        // Add a small delay to ensure backend is ready
        setTimeout(async () => {
          // Auto-detect archive tool if seven_zip_bin is not set
          if (!settings.seven_zip_bin || settings.seven_zip_bin.trim() === "") {
            try {
              const result = await invoke<{
                success: boolean;
                name?: string;
                executable?: string;
                message: string;
                already_in_path?: boolean;
              }>("detect_archive_tool");

              if (result.success && result.executable) {
                setFormValues((prev) => ({
                  ...prev,
                  seven_zip_bin: result.executable!,
                }));

                if (result.already_in_path) {
                  toast.info(`${result.name} detected`, {
                    description: `Already in PATH: ${result.executable}`,
                    duration: 4000,
                  });
                } else {
                  toast.success(`${result.name} detected and added to PATH`, {
                    description: `Executable: ${result.executable}`,
                    duration: 4000,
                  });
                }
              }
            } catch (error) {
              console.error("Archive tool auto-detect failed:", error);
              // Silently fail - user can manually detect later
            }
          }
        }, 100); // Small delay to ensure backend is ready
      };

      // Auto-detect Marvel Rivals path if not set
      const detectMarvelRivalsPath = async () => {
        if (
          !settings.marvel_rivals_root ||
          settings.marvel_rivals_root.trim() === ""
        ) {
          try {
            const result = await invoke<{
              success: boolean;
              path?: string;
              message: string;
            }>("detect_marvel_rivals_path");

            if (result.success && result.path) {
              setFormValues((prev) => ({
                ...prev,
                marvel_rivals_root: result.path!,
              }));
              toast.success("Marvel Rivals detected", {
                description: `Found at: ${result.path}`,
                duration: 4000,
              });
            }
          } catch (error) {
            console.log("Marvel Rivals detection failed:", error);
            // Silently fail - user can manually detect later
          }
        }
      };

      // Run detection
      detectMarvelRivalsPath();

      autoDetectSidecars();
    }
  }, [open, settings]);

  useEffect(() => {
    if (!open) {
      return;
    }
    if (jobRunning) {
      if (stage !== "running") {
        console.log("[GetStarted] Transitioning to running stage");
        setStage("running");
      }
      return;
    }
    if (stage === "running" && !jobRunning) {
      console.log(
        "[GetStarted] Job completed, checking status:",
        job?.status,
        "ok:",
        job?.ok,
      );
      const succeeded = job?.status === "succeeded" && job?.ok === true;
      const failed =
        job?.status === "failed" ||
        (job?.status === "succeeded" && job?.ok === false);
      if (succeeded) {
        console.log("[GetStarted] Success! Transitioning to complete stage");
        setStage("complete");
        setErrorMessage(null);
        return;
      }
      if (failed) {
        console.log("[GetStarted] Failed! Transitioning back to ready stage");
        setStage("ready");
        setErrorMessage(
          job?.error?.trim() ||
            "Initial database build failed. Review the output below and try again.",
        );
        return;
      }
      console.log("[GetStarted] Job in intermediate state, waiting...");
    }
  }, [open, jobRunning, job, stage]);

  const isSaving = savingSettings || loadingSettings;

  const requiredValidationOk = useMemo(() => {
    const validation = settings?.validation;
    if (!validation) return false;
    const keys: Array<keyof typeof validation> = [
      "data_dir",
      "marvel_rivals_root",
      "marvel_rivals_local_downloads_root",
    ];
    return keys.every((key) => validation[key]?.ok);
  }, [settings]);

  const handleInputChange =
    (field: Exclude<keyof SettingsFormValues, "allow_direct_api_downloads">) =>
    (event: ChangeEvent<HTMLInputElement>) => {
      const value = event.target.value;
      setFormValues((prev) => ({ ...prev, [field]: value }));

      // Clear previous validation result
      setPathCheckResults((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });

      // Clear existing debounce timer for this field
      if (debounceTimers[field]) {
        clearTimeout(debounceTimers[field]);
      }

      // Only validate path fields
      const pathFields = new Set([
        "data_dir",
        "marvel_rivals_root",
        "marvel_rivals_local_downloads_root",
      ]);

      if (!pathFields.has(field) || !value.trim()) {
        return;
      }

      // Set new debounce timer (500ms after user stops typing)
      debounceTimers[field] = setTimeout(async () => {
        setValidatingFields((prev) => new Set(prev).add(field));

        try {
          const result = await validatePath(field, value);
          setPathCheckResults((prev) => ({
            ...prev,
            [field]: {
              ok: result.ok,
              message: result.message,
            },
          }));
        } catch (err) {
          setPathCheckResults((prev) => ({
            ...prev,
            [field]: {
              ok: false,
              message: "Error validating path",
            },
          }));
          console.error(`Failed to validate ${field}:`, err);
        } finally {
          setValidatingFields((prev) => {
            const next = new Set(prev);
            next.delete(field);
            return next;
          });
        }
      }, 500);
    };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSaving) return;
    setErrorMessage(null);
    const ok = await onSubmit(formValues);
    if (ok) {
      setStage("ready");
      onRefreshSettings();
      onRefreshStatus();
    } else {
      setErrorMessage(
        "Unable to save settings. Resolve the highlighted fields and try again.",
      );
    }
  };

  const handleRunBootstrapClick = async () => {
    setErrorMessage(null);

    // CRITICAL: Save settings BEFORE running bootstrap so the rebuild script
    // can read the latest configuration (API key, paths, etc.) from disk
    console.log("[GetStartedDialog] Saving settings before bootstrap...");
    const settingsSaved = await onSubmit(formValues);
    if (!settingsSaved) {
      setErrorMessage(
        "Unable to save settings. Please fix any errors and try again.",
      );
      return;
    }
    console.log(
      "[GetStartedDialog] Settings saved successfully, starting bootstrap...",
    );

    // Small delay to ensure settings.json is fully written to disk before subprocess reads it
    await new Promise((resolve) => setTimeout(resolve, 200));

    setStage("running");
    const ok = await onRunBootstrap();
    if (ok) {
      setStage("complete");
      onRefreshStatus();
    } else {
      setStage("ready");
      setErrorMessage(
        "Initial database build failed. Review the output below and try again.",
      );
    }
  };

  const handleRefreshValidation = () => {
    onRefreshSettings();
    onRefreshStatus();
  };

  const handleNexusSso = async () => {
    setIsNexusSsoLoading(true);
    setNexusSsoStatus(null);
    setErrorMessage(null);

    try {
      const result = await initiateNexusSso(
        NEXUS_APPLICATION_SLUG,
        (status) => {
          setNexusSsoStatus(status);
        },
      );

      if (result.success && result.apiKey) {
        // Successfully received API key
        setFormValues((prev) => ({
          ...prev,
          nexus_api_key: result.apiKey!,
        }));
        toast.success("Successfully signed in with Nexus!", {
          description: "Your API key has been retrieved automatically.",
          duration: 5000,
        });
        setNexusSsoStatus({
          stage: "authorized",
          message: "API key retrieved successfully!",
        });
      } else {
        // SSO failed
        setNexusSsoStatus({
          stage: "error",
          message: result.error || "SSO authentication failed",
        });
        toast.error("Nexus SSO failed", {
          description:
            result.error || "Please try again or use manual API key entry.",
          duration: 5000,
        });
      }
    } catch (error) {
      console.error("[GetStartedDialog] SSO error:", error);
      setNexusSsoStatus({
        stage: "error",
        message: "An unexpected error occurred",
      });
      toast.error("Nexus SSO failed", {
        description:
          "An unexpected error occurred. Please try manual API key entry.",
        duration: 5000,
      });
    } finally {
      setIsNexusSsoLoading(false);
    }
  };

  const handleDialogOpenChange = (nextOpen: boolean) => {
    const canClose = !jobRunning || stage === "complete";
    if (!nextOpen && !canClose) {
      return;
    }
    onOpenChange(nextOpen);
  };

  const handleFolderSelect = async (field: string) => {
    try {
      const result = await invoke<string>("select_folder_dialog", {
        defaultPath: null,
      });

      if (result) {
        setFormValues((prev) => ({ ...prev, [field]: result }));
        // Clear previous validation result
        setPathCheckResults((prev) => {
          const next = { ...prev };
          delete next[field];
          return next;
        });
      }
    } catch (error) {
      console.error(`Failed to select folder for ${field}:`, error);
      if (error !== "Selection cancelled") {
        alert(`Failed to select folder: ${error}`);
      }
    }
  };

  const handleFileSelect = async (field: string) => {
    try {
      const result = await invoke<string>("select_file_dialog", {
        defaultPath: null,
        filterExtensions:
          field === "seven_zip_bin" ? ["exe", "bat", "cmd", "msi"] : ["*"],
      });

      if (result) {
        setFormValues((prev) => ({ ...prev, [field]: result }));
      }
    } catch (error) {
      console.error(`Failed to select file for ${field}:`, error);
      if (error !== "Selection cancelled") {
        alert(`Failed to select file: ${error}`);
      }
    }
  };

  const bootstrapSummary = bootstrapStatus ? (
    <div className="mt-4 rounded-lg border border-border/40 bg-muted/10 p-4 text-sm">
      <div
        className={`flex items-center gap-2 ${
          bootstrapStatus.needs_bootstrap
            ? "text-amber-500"
            : "text-emerald-500"
        }`}
      >
        <CheckCircle className="h-4 w-4" />
        <span>
          {bootstrapStatus.needs_bootstrap
            ? "Database is empty. The initial build will populate all tables."
            : "Database already contains records. Rerunning will refresh everything."}
        </span>
      </div>
      <div
        className="mt-3 grid gap-3 text-xs text-muted-foreground"
        style={{ gridTemplateColumns: "60% 40%" }}
      >
        <div>
          <p className="font-semibold text-foreground">Database file</p>
          <p className="break-all">
            {bootstrapStatus.db_path || "(not detected)"}
          </p>
        </div>
        <div>
          <p className="font-semibold text-foreground">Existing downloads</p>
          <p>{bootstrapStatus.downloads_count}</p>
        </div>
        <div>
          <p className="font-semibold text-foreground">Mods loaded</p>
          <p>{bootstrapStatus.mods_count}</p>
        </div>
        <div>
          <p className="font-semibold text-foreground">Schema migrations</p>
          <p>{bootstrapStatus.schema_migrations}</p>
        </div>
      </div>
    </div>
  ) : null;

  const disableRunBootstrap = jobRunning;

  const jobOutput = job?.output?.trim() ?? "";

  return (
    <Dialog open={open} onOpenChange={handleDialogOpenChange}>
      <DialogContent
        style={{
          maxWidth: "48rem",
          width: "100%",
          maxHeight: "calc(100vh - 48px)",
          minHeight: "320px",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          padding: "0",
        }}
      >
        <div
          className="getstarted-dialog-scroll"
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "2rem",
            boxSizing: "border-box",
            // Traditional CSS to hide scrollbars while keeping functionality
            msOverflowStyle: "none", // IE and Edge
            scrollbarWidth: "none", // Firefox
          }}
        >
          <style>{`
            .getstarted-dialog-scroll::-webkit-scrollbar {
              display: none;
            }
          `}</style>
          <DialogHeader>
            <DialogTitle className="text-2xl font-semibold">
              Welcome to RivalNxt
            </DialogTitle>
            <DialogDescription className="text-sm text-muted-foreground">
              Configure the core folders and tools, then build the local
              database with a guided setup.
            </DialogDescription>
          </DialogHeader>

          {stage === "collect" ? (
            <form
              onSubmit={handleSubmit}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "1.5rem",
                marginTop: "1.5rem",
              }}
            >
              {/* Progress Indicator */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "center",
                  gap: "0.5rem",
                  marginBottom: "0.5rem",
                }}
              >
                {[1, 2, 3].map((step) => (
                  <div
                    key={step}
                    style={{
                      width: "2.5rem",
                      height: "0.25rem",
                      borderRadius: "0.125rem",
                      background:
                        step <= wizardStep
                          ? "linear-gradient(90deg, #8b5cf6, #a855f7)"
                          : "rgba(107, 114, 128, 0.3)",
                      transition: "background 0.3s ease",
                    }}
                  />
                ))}
              </div>
              <div
                style={{
                  textAlign: "center",
                  fontSize: "0.75rem",
                  color: "#6b7280",
                }}
              >
                Step {wizardStep} of 3
              </div>

              <style>{`.custom-scrollbar::-webkit-scrollbar {
            display: none;
          }
          .custom-scrollbar {
            msOverflowStyle: none;
            scrollbar-width: none;
          }`}</style>

              {/* Step 1: Local Download Folder */}
              {wizardStep === 1 && (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "1.5rem",
                  }}
                >
                  <div
                    style={{
                      textAlign: "center",
                      padding: "1rem",
                    }}
                  >
                    <h3
                      style={{
                        fontSize: "1.25rem",
                        fontWeight: "600",
                        marginBottom: "0.5rem",
                      }}
                    >
                      Choose Local Download Folder
                    </h3>
                    <p
                      style={{
                        fontSize: "0.875rem",
                        color: "#6b7280",
                        lineHeight: "1.6",
                      }}
                    >
                      Choose the dedicated folder where all your previously
                      downloaded mod archives/folders are stored. If you don't
                      have a dedicated mod folder yet, create one and keep all
                      your mods there. If you have no previous mods, simply
                      create a new empty folder and select it.
                    </p>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="marvel_rivals_local_downloads_root">
                      Local downloads folder
                    </Label>
                    <div
                      style={{
                        display: "flex",
                        gap: "0.5rem",
                        alignItems: "center",
                      }}
                    >
                      <Input
                        id="marvel_rivals_local_downloads_root"
                        placeholder="...\\Marvel_Rivals_Mods\\downloads"
                        value={formValues.marvel_rivals_local_downloads_root}
                        onChange={handleInputChange(
                          "marvel_rivals_local_downloads_root",
                        )}
                        className="flex-1"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          handleFolderSelect(
                            "marvel_rivals_local_downloads_root",
                          )
                        }
                        style={{ padding: "0.5rem", minWidth: "auto" }}
                        title="Select folder"
                      >
                        <Folder className="h-4 w-4" />
                      </Button>
                    </div>
                    {pathCheckResults.marvel_rivals_local_downloads_root && (
                      <p
                        style={{
                          fontSize: "0.75rem",
                          color: pathCheckResults
                            .marvel_rivals_local_downloads_root.ok
                            ? "#059669"
                            : "#dc2626",
                          marginTop: "0.25rem",
                          display: "flex",
                          alignItems: "center",
                          gap: "0.25rem",
                        }}
                      >
                        {pathCheckResults.marvel_rivals_local_downloads_root
                          .ok ? (
                          <CheckCircle
                            style={{ width: "0.875rem", height: "0.875rem" }}
                          />
                        ) : (
                          <AlertCircle
                            style={{ width: "0.875rem", height: "0.875rem" }}
                          />
                        )}
                        {
                          pathCheckResults.marvel_rivals_local_downloads_root
                            .message
                        }
                      </p>
                    )}
                    <p
                      style={{
                        fontSize: "0.75rem",
                        color: "#6b7280",
                        marginTop: "0.5rem",
                      }}
                    >
                      💡 Tip: The folder will be created automatically if it
                      doesn't exist.
                    </p>
                  </div>

                  <div className="flex items-center justify-between">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => onOpenChange(false)}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="button"
                      disabled={
                        !formValues.marvel_rivals_local_downloads_root?.trim()
                      }
                      onClick={() => setWizardStep(2)}
                    >
                      Continue
                    </Button>
                  </div>
                </div>
              )}

              {/* Step 2: API Key */}
              {wizardStep === 2 && (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "1.5rem",
                  }}
                >
                  <div
                    style={{
                      textAlign: "center",
                      padding: "1rem",
                    }}
                  >
                    <h3
                      style={{
                        fontSize: "1.25rem",
                        fontWeight: "600",
                        marginBottom: "0.5rem",
                      }}
                    >
                      Connect to Nexus Mods
                    </h3>
                    <p
                      style={{
                        fontSize: "0.875rem",
                        color: "#6b7280",
                        lineHeight: "1.6",
                      }}
                    >
                      The API key allows RivalNxt to fetch mod details,
                      descriptions, and images directly from NexusMods. Without
                      it, only basic local mod management will work.
                    </p>
                  </div>

                  {/* Two-column layout */}
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: "1rem",
                    }}
                  >
                    {/* Left Column: Sign in with Nexus SSO */}
                    <div
                      style={{
                        borderRadius: "0.5rem",
                        background: "rgba(59, 130, 246, 0.1)",
                        border: "1px solid rgba(59, 130, 246, 0.3)",
                        padding: "1rem",
                        display: "flex",
                        flexDirection: "column",
                        justifyContent: "space-between",
                      }}
                    >
                      <div>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "0.5rem",
                            marginBottom: "0.75rem",
                          }}
                        >
                          <LogIn className="h-4 w-4 text-blue-400" />
                          <p
                            style={{
                              fontSize: "0.875rem",
                              fontWeight: "600",
                              color: "#60a5fa",
                            }}
                          >
                            Sign in with Nexus
                          </p>
                        </div>
                        <p
                          style={{
                            fontSize: "0.8rem",
                            color: "#9ca3af",
                            lineHeight: "1.6",
                            marginBottom: "0.75rem",
                          }}
                        >
                          One-click sign in. Opens your browser for secure
                          authorization with Nexus Mods.
                        </p>
                      </div>

                      <div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={handleNexusSso}
                          disabled={isNexusSsoLoading}
                          style={{
                            width: "100%",
                            borderColor: "rgba(59, 130, 246, 0.5)",
                            color: "#60a5fa",
                          }}
                        >
                          {isNexusSsoLoading ? (
                            <>
                              <Loader2 className="h-3 w-3 mr-2 animate-spin" />
                              {nexusSsoStatus?.stage === "connecting"
                                ? "Connecting..."
                                : nexusSsoStatus?.stage === "waiting"
                                  ? "Waiting for authorization..."
                                  : "Please wait..."}
                            </>
                          ) : (
                            <>
                              <LogIn className="h-3 w-3 mr-2" />
                              Sign in with Nexus
                            </>
                          )}
                        </Button>

                        {/* SSO Status */}
                        {nexusSsoStatus && (
                          <p
                            style={{
                              fontSize: "0.75rem",
                              marginTop: "0.5rem",
                              display: "flex",
                              alignItems: "center",
                              gap: "0.25rem",
                              color:
                                nexusSsoStatus.stage === "authorized"
                                  ? "#10b981"
                                  : nexusSsoStatus.stage === "error"
                                    ? "#ef4444"
                                    : "#60a5fa",
                            }}
                          >
                            {nexusSsoStatus.stage === "authorized" ? (
                              <CheckCircle
                                style={{
                                  width: "0.75rem",
                                  height: "0.75rem",
                                }}
                              />
                            ) : nexusSsoStatus.stage === "error" ? (
                              <AlertCircle
                                style={{
                                  width: "0.75rem",
                                  height: "0.75rem",
                                }}
                              />
                            ) : (
                              <Loader2
                                className="animate-spin"
                                style={{
                                  width: "0.75rem",
                                  height: "0.75rem",
                                }}
                              />
                            )}
                            {nexusSsoStatus.message}
                          </p>
                        )}
                      </div>
                    </div>

                    {/* Right Column: Manual API Key Entry */}
                    <div
                      style={{
                        borderRadius: "0.5rem",
                        background: "rgba(139, 92, 246, 0.1)",
                        border: "1px solid rgba(139, 92, 246, 0.3)",
                        padding: "1rem",
                      }}
                    >
                      <p
                        style={{
                          fontSize: "0.875rem",
                          fontWeight: "500",
                          marginBottom: "0.75rem",
                        }}
                      >
                        Or get API key manually:
                      </p>
                      <ol
                        style={{
                          fontSize: "0.75rem",
                          color: "#9ca3af",
                          paddingLeft: "1.25rem",
                          lineHeight: "1.6",
                        }}
                      >
                        <li>Click "Get API Key" to open NexusMods</li>
                        <li>Sign in to your account if prompted</li>
                        <li>Find "RivalNxt" in API keys list</li>
                        <li>Copy and paste the key below</li>
                      </ol>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={async () => {
                          const apiKeysUrl =
                            "https://next.nexusmods.com/settings/api-keys#:~:text=Rivalnxt";
                          try {
                            const { openInBrowser } =
                              await import("../lib/tauri-utils");
                            await openInBrowser(apiKeysUrl);
                          } catch (error) {
                            console.error(
                              "Failed to open API keys page:",
                              error,
                            );
                          }
                        }}
                        style={{ marginTop: "0.75rem" }}
                      >
                        <ExternalLink className="h-3 w-3 mr-2" />
                        Get API Key
                      </Button>
                    </div>
                  </div>

                  {/* API Key Input (shared by both methods) */}
                  <div className="space-y-2">
                    <Label htmlFor="nexus_api_key">Nexus API key</Label>
                    <Input
                      id="nexus_api_key"
                      type="password"
                      placeholder="•••••••••••••••"
                      value={formValues.nexus_api_key}
                      onChange={handleInputChange("nexus_api_key")}
                    />
                    {/* Show SSO success message if key was autofilled via SSO */}
                    {nexusSsoStatus?.stage === "authorized" &&
                    formValues.nexus_api_key ? (
                      <p
                        style={{
                          fontSize: "0.75rem",
                          color: "#059669",
                          marginTop: "0.25rem",
                          display: "flex",
                          alignItems: "center",
                          gap: "0.25rem",
                        }}
                      >
                        <CheckCircle
                          style={{ width: "0.875rem", height: "0.875rem" }}
                        />
                        API key retrieved via Sign in with Nexus
                      </p>
                    ) : settings?.validation?.nexus_api_key ? (
                      <p
                        style={{
                          fontSize: "0.75rem",
                          color: settings.validation.nexus_api_key.ok
                            ? "#059669"
                            : settings.validation.nexus_api_key.reason ===
                                "not_configured"
                              ? "#6b7280"
                              : "#dc2626",
                          marginTop: "0.25rem",
                          display: "flex",
                          alignItems: "center",
                          gap: "0.25rem",
                        }}
                      >
                        {settings.validation.nexus_api_key.ok ? (
                          <CheckCircle
                            style={{ width: "0.875rem", height: "0.875rem" }}
                          />
                        ) : (
                          <AlertCircle
                            style={{ width: "0.875rem", height: "0.875rem" }}
                          />
                        )}
                        {settings.validation.nexus_api_key.message?.trim() ||
                          ""}
                      </p>
                    ) : null}
                  </div>

                  <div className="flex items-center justify-between">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setWizardStep(1)}
                    >
                      Back
                    </Button>
                    <Button
                      type="button"
                      disabled={!formValues.nexus_api_key?.trim()}
                      onClick={() => setWizardStep(3)}
                    >
                      Continue
                    </Button>
                  </div>
                </div>
              )}

              {/* Step 3: Remaining Settings */}
              {wizardStep === 3 && (
                <div
                  className="custom-scrollbar"
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "1.5rem",
                  }}
                >
                  <div
                    style={{
                      textAlign: "center",
                      padding: "0.5rem 1rem",
                    }}
                  >
                    <h3
                      style={{
                        fontSize: "1.25rem",
                        fontWeight: "600",
                        marginBottom: "0.5rem",
                      }}
                    >
                      Configure Remaining Settings
                    </h3>
                    <p
                      style={{
                        fontSize: "0.875rem",
                        color: "#6b7280",
                      }}
                    >
                      Review your configuration and set up the remaining paths.
                    </p>
                  </div>

                  <div
                    style={{
                      maxHeight: "20rem",
                      overflowY: "auto",
                      paddingRight: "0.5rem",
                    }}
                    className="custom-scrollbar"
                  >
                    <div
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: "1rem",
                      }}
                    >
                      {/* Previously entered values - auto-populated */}
                      <div className="space-y-2">
                        <Label htmlFor="step3_marvel_rivals_local_downloads_root">
                          Local downloads folder
                        </Label>
                        <div
                          style={{
                            display: "flex",
                            gap: "0.5rem",
                            alignItems: "center",
                          }}
                        >
                          <Input
                            id="step3_marvel_rivals_local_downloads_root"
                            placeholder="...\\Marvel_Rivals_Mods\\downloads"
                            value={
                              formValues.marvel_rivals_local_downloads_root
                            }
                            onChange={handleInputChange(
                              "marvel_rivals_local_downloads_root",
                            )}
                            className="flex-1"
                          />
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              handleFolderSelect(
                                "marvel_rivals_local_downloads_root",
                              )
                            }
                            style={{ padding: "0.5rem", minWidth: "auto" }}
                            title="Select folder"
                          >
                            <Folder className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="step3_nexus_api_key">
                          Nexus API key
                        </Label>
                        <Input
                          id="step3_nexus_api_key"
                          type="password"
                          placeholder="•••••••••••••••"
                          value={formValues.nexus_api_key}
                          onChange={handleInputChange("nexus_api_key")}
                        />
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="marvel_rivals_root">
                          Marvel Rivals root
                        </Label>
                        <div
                          style={{
                            display: "flex",
                            gap: "0.5rem",
                            alignItems: "center",
                          }}
                        >
                          <Input
                            id="marvel_rivals_root"
                            placeholder="...\\SteamLibrary\\steamapps\\common\\MarvelRivals"
                            value={formValues.marvel_rivals_root}
                            onChange={handleInputChange("marvel_rivals_root")}
                            className="flex-1"
                          />
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={async () => {
                              try {
                                const result = await invoke<{
                                  success: boolean;
                                  path?: string;
                                  message: string;
                                }>("detect_marvel_rivals_path");

                                if (result.success && result.path) {
                                  setFormValues((prev) => ({
                                    ...prev,
                                    marvel_rivals_root: result.path!,
                                  }));
                                  toast.success("Marvel Rivals detected", {
                                    description: `Found at: ${result.path}`,
                                    duration: 4000,
                                  });
                                } else {
                                  toast.error("Marvel Rivals not found", {
                                    description:
                                      result.message ||
                                      "Installation not detected. Please install via Steam or Epic Games Store.",
                                    duration: 4000,
                                  });
                                }
                              } catch (error) {
                                console.error(
                                  "Failed to detect Marvel Rivals:",
                                  error,
                                );
                                toast.error("Detection failed", {
                                  description: String(error),
                                  duration: 4000,
                                });
                              }
                            }}
                            style={{ padding: "0.5rem", minWidth: "auto" }}
                            title="Auto-detect Marvel Rivals installation"
                          >
                            <RotateCcw className="h-4 w-4" />
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              handleFolderSelect("marvel_rivals_root")
                            }
                            style={{ padding: "0.5rem", minWidth: "auto" }}
                            title="Select folder"
                          >
                            <Folder className="h-4 w-4" />
                          </Button>
                        </div>
                        {pathCheckResults.marvel_rivals_root && (
                          <p
                            style={{
                              fontSize: "0.75rem",
                              color: pathCheckResults.marvel_rivals_root.ok
                                ? "#059669"
                                : "#dc2626",
                              marginTop: "0.25rem",
                              display: "flex",
                              alignItems: "center",
                              gap: "0.25rem",
                            }}
                          >
                            {pathCheckResults.marvel_rivals_root.ok ? (
                              <CheckCircle
                                style={{
                                  width: "0.875rem",
                                  height: "0.875rem",
                                }}
                              />
                            ) : (
                              <AlertCircle
                                style={{
                                  width: "0.875rem",
                                  height: "0.875rem",
                                }}
                              />
                            )}
                            {pathCheckResults.marvel_rivals_root.message}
                          </p>
                        )}
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="seven_zip_bin">WinRAR executable</Label>
                        <div
                          style={{
                            display: "flex",
                            gap: "0.5rem",
                            alignItems: "center",
                          }}
                        >
                          <Input
                            id="seven_zip_bin"
                            placeholder="C:\\Program Files\\WinRAR\\WinRAR.exe"
                            value={formValues.seven_zip_bin}
                            onChange={handleInputChange("seven_zip_bin")}
                            className="flex-1"
                          />
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={async () => {
                              try {
                                const result = await invoke<{
                                  success: boolean;
                                  name?: string;
                                  executable?: string;
                                  message: string;
                                  already_in_path?: boolean;
                                }>("detect_archive_tool");

                                if (result.success && result.executable) {
                                  setFormValues((prev) => ({
                                    ...prev,
                                    seven_zip_bin: result.executable!,
                                  }));

                                  if (result.already_in_path) {
                                    toast.info(`${result.name} detected`, {
                                      description: `Already in PATH: ${result.executable}`,
                                      duration: 4000,
                                    });
                                  } else {
                                    toast.success(
                                      `${result.name} detected and added to PATH`,
                                      {
                                        description: `Executable: ${result.executable}`,
                                        duration: 4000,
                                      },
                                    );
                                  }
                                } else {
                                  toast.error("Archive tool not found", {
                                    description:
                                      result.message ||
                                      "WinRAR installation not found",
                                    duration: 4000,
                                  });
                                }
                              } catch (error) {
                                console.error(
                                  "Failed to detect archive tool:",
                                  error,
                                );
                                toast.error("Detection failed", {
                                  description: String(error),
                                  duration: 4000,
                                });
                              }
                            }}
                            style={{ padding: "0.5rem", minWidth: "auto" }}
                            title="Auto-detect WinRAR"
                          >
                            <RotateCcw className="h-4 w-4" />
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => handleFileSelect("seven_zip_bin")}
                            style={{ padding: "0.5rem", minWidth: "auto" }}
                            title="Select file"
                          >
                            <Folder className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="aes_key_hex">AES key</Label>
                        <Input
                          id="aes_key_hex"
                          type="password"
                          placeholder="hex-encoded key"
                          value={formValues.aes_key_hex}
                          onChange={handleInputChange("aes_key_hex")}
                        />
                        <p className="text-xs text-muted-foreground">
                          Already filled in. Lets the app read the asset list
                          inside a mod's .pak files, which powers tags and
                          conflict detection. Not a personal key — leave as is.
                        </p>
                      </div>

                      <div className="space-y-2">
                        <Label htmlFor="data_dir">
                          Data directory (Locked)
                        </Label>
                        <div
                          style={{
                            display: "flex",
                            gap: "0.5rem",
                            alignItems: "center",
                          }}
                        >
                          <Input
                            id="data_dir"
                            placeholder="C:\\Users\\You\\AppData\\Local\\RivalsManager"
                            value={formValues.data_dir}
                            readOnly
                            className="flex-1 bg-muted/50"
                          />
                        </div>
                      </div>
                    </div>
                  </div>

                  {errorMessage ? (
                    <div className="flex items-start gap-2 rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-500">
                      <AlertCircle className="mt-0.5 h-4 w-4" />
                      <span>{errorMessage}</span>
                    </div>
                  ) : null}

                  <div className="flex items-center justify-between">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setWizardStep(2)}
                    >
                      Back
                    </Button>
                    <Button
                      type="submit"
                      disabled={
                        isSaving ||
                        !formValues.marvel_rivals_local_downloads_root?.trim() ||
                        !formValues.nexus_api_key?.trim()
                      }
                    >
                      {isSaving ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Saving
                        </>
                      ) : (
                        "Save & Continue"
                      )}
                    </Button>
                  </div>
                </div>
              )}
            </form>
          ) : null}

          {stage === "ready" ? (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "1.5rem",
                marginTop: "1.5rem",
              }}
            >
              <div className="flex items-start gap-3 rounded-lg border border-border/40 bg-muted/5 p-4">
                <Hammer className="mt-1 h-5 w-5 text-primary" />
                <div className="space-y-2 text-sm">
                  <p className="font-medium text-foreground">
                    Settings saved. Run the initial database build when you are
                    ready.
                  </p>
                  <p className="text-muted-foreground">
                    This will scan your downloads, ingest pak metadata, sync
                    Nexus details, rebuild tags, and refresh conflict tables.
                  </p>
                </div>
              </div>

              {bootstrapSummary}

              {!requiredValidationOk ? (
                <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-500">
                  <AlertCircle className="mt-0.5 h-4 w-4" />
                  <span>
                    One or more required directories still needs attention.
                    Update the paths before running the build.
                  </span>
                </div>
              ) : null}

              {errorMessage ? (
                <div className="flex items-start gap-2 rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-500">
                  <AlertCircle className="mt-0.5 h-4 w-4" />
                  <span>{errorMessage}</span>
                </div>
              ) : null}

              {jobOutput ? (
                <div className="space-y-2">
                  <Label>Last run output</Label>
                  <TaskOutputSummary
                    task={job?.task ?? "bootstrap_rebuild"}
                    output={jobOutput}
                    style={{ minHeight: "200px" }}
                  />
                </div>
              ) : null}

              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleRefreshValidation}
                    disabled={jobRunning}
                  >
                    <RotateCcw className="mr-2 h-4 w-4" />
                    Refresh status
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setStage("collect")}
                    disabled={jobRunning}
                  >
                    Edit paths
                  </Button>
                </div>
                <Button
                  type="button"
                  onClick={handleRunBootstrapClick}
                  disabled={disableRunBootstrap || !requiredValidationOk}
                >
                  {jobRunning ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Starting…
                    </>
                  ) : (
                    "Run initial build"
                  )}
                </Button>
              </div>
            </div>
          ) : null}

          {stage === "running" ? (
            <div className="space-y-4" style={{ marginTop: "1.5rem" }}>
              <div className="space-y-2">
                <Label>Task output</Label>
                <TaskOutputSummary
                  task={job?.task ?? "bootstrap_rebuild"}
                  output={jobOutput}
                  isRunning={jobRunning}
                  startedAt={job?.started_at ?? null}
                  style={{ minHeight: "200px" }}
                />
              </div>
            </div>
          ) : null}

          {stage === "complete" ? (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "1.5rem",
                marginTop: "1.5rem",
              }}
            >
              <div className="flex items-start gap-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-4">
                <CheckCircle className="mt-0.5 h-5 w-5 text-emerald-500" />
                <div className="space-y-1 text-sm">
                  <p className="font-medium text-foreground">Finished</p>
                  <p className="text-muted-foreground">
                    <code className="rounded bg-emerald-500/20 px-1 py-0.5 text-xs text-emerald-100">
                      [rebuild_sqlite] Rebuild completed successfully.
                    </code>{" "}
                    All tables have been refreshed.
                  </p>
                </div>
              </div>
              <div className="space-y-2">
                <Label>Task output</Label>
                <TaskOutputSummary
                  task={job?.task ?? "bootstrap_rebuild"}
                  output={jobOutput}
                  style={{ minHeight: "200px" }}
                />
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "flex-end",
                  gap: "0.75rem",
                }}
              >
                <Button variant="outline" onClick={() => setStage("ready")}>
                  View status
                </Button>
                <Button onClick={() => onOpenChange(false)}>
                  Finished – View Mods
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
