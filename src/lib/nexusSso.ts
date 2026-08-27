/**
 * Nexus Mods SSO Authentication Service
 *
 * Implements the Nexus Mods SSO WebSocket flow for automatic API key retrieval.
 * Reference: https://github.com/Nexus-Mods/sso-integration-demo
 */

import { openInBrowser } from "./tauri-utils";

// SSO WebSocket endpoint
const SSO_WEBSOCKET_URL = "wss://sso.nexusmods.com";

// Nexus SSO authorization page base URL
const SSO_AUTH_URL = "https://www.nexusmods.com/sso";

// Application slug for RivalNxt (registered with Nexus Mods)
// Testing lowercase version due to 404 error with original casing
export const NEXUS_APPLICATION_SLUG = "rounak77382-rivalnxt";

// Timeout for SSO flow (5 minutes)
const SSO_TIMEOUT_MS = 5 * 60 * 1000;

/**
 * Response structure from Nexus SSO WebSocket
 */
export type NexusSsoResponse = {
  success: boolean;
  data?: {
    connection_token?: string;
    api_key?: string;
  };
  error?: string | null;
};

/**
 * Result of the SSO flow
 */
export type NexusSsoResult = {
  success: boolean;
  apiKey?: string;
  error?: string;
};

/**
 * Callback for SSO status updates
 */
export type NexusSsoStatusCallback = (status: {
  stage: "connecting" | "waiting" | "authorized" | "error";
  message: string;
}) => void;

/**
 * Generate a UUID v4
 */
function generateUuid(): string {
  // Use crypto API if available, otherwise fallback
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }

  // Fallback UUID v4 generation
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * Initiate the Nexus SSO authentication flow
 *
 * @param applicationSlug - The application slug registered with Nexus Mods
 * @param onStatusChange - Optional callback for status updates
 * @returns Promise that resolves with the API key or error
 */
export async function initiateNexusSso(
  applicationSlug: string = NEXUS_APPLICATION_SLUG,
  onStatusChange?: NexusSsoStatusCallback,
): Promise<NexusSsoResult> {
  return new Promise((resolve) => {
    let socket: WebSocket | null = null;
    let timeoutId: NodeJS.Timeout | null = null;
    let resolved = false;

    const cleanup = () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
        timeoutId = null;
      }
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.close();
      }
      socket = null;
    };

    const resolveOnce = (result: NexusSsoResult) => {
      if (resolved) return;
      resolved = true;
      cleanup();
      resolve(result);
    };

    // Set timeout for the entire flow
    timeoutId = setTimeout(() => {
      onStatusChange?.({
        stage: "error",
        message: "SSO authentication timed out. Please try again.",
      });
      resolveOnce({
        success: false,
        error:
          "SSO authentication timed out after 5 minutes. Please try again.",
      });
    }, SSO_TIMEOUT_MS);

    try {
      onStatusChange?.({
        stage: "connecting",
        message: "Connecting to Nexus Mods...",
      });

      // Generate a unique session ID
      const uuid = generateUuid();
      console.log("[NexusSSO] Generated UUID:", uuid);

      // Create WebSocket connection
      socket = new WebSocket(SSO_WEBSOCKET_URL);

      socket.onopen = () => {
        console.log("[NexusSSO] WebSocket connected");

        // Send initial handshake
        const handshake = {
          id: uuid,
          token: null, // No token for first connection
          protocol: 2,
        };

        console.log("[NexusSSO] Sending handshake:", handshake);
        socket?.send(JSON.stringify(handshake));
      };

      socket.onmessage = async (event) => {
        console.log("[NexusSSO] Received message:", event.data);

        try {
          const response: NexusSsoResponse = JSON.parse(event.data);

          if (!response.success) {
            onStatusChange?.({
              stage: "error",
              message: response.error || "SSO authentication failed",
            });
            resolveOnce({
              success: false,
              error: response.error || "SSO authentication failed",
            });
            return;
          }

          // Check if we received the API key
          if (response.data?.api_key) {
            console.log("[NexusSSO] Received API key!");
            onStatusChange?.({
              stage: "authorized",
              message: "Successfully authenticated with Nexus Mods!",
            });
            resolveOnce({
              success: true,
              apiKey: response.data.api_key,
            });
            return;
          }

          // Check if we received connection token (handshake complete)
          if (response.data?.connection_token) {
            console.log(
              "[NexusSSO] Received connection token, opening browser...",
            );

            onStatusChange?.({
              stage: "waiting",
              message:
                "Waiting for authorization... Please complete sign-in in your browser.",
            });

            // Open browser to authorization page
            const authUrl = `${SSO_AUTH_URL}?id=${encodeURIComponent(uuid)}&application=${encodeURIComponent(applicationSlug)}`;
            console.log("[NexusSSO] Opening auth URL:", authUrl);

            try {
              await openInBrowser(authUrl);
            } catch (browserError) {
              console.error("[NexusSSO] Failed to open browser:", browserError);
              onStatusChange?.({
                stage: "error",
                message: "Failed to open browser for authorization",
              });
              resolveOnce({
                success: false,
                error: "Failed to open browser for authorization",
              });
            }
          }
        } catch (parseError) {
          console.error("[NexusSSO] Failed to parse response:", parseError);
        }
      };

      socket.onerror = (error) => {
        console.error("[NexusSSO] WebSocket error:", error);
        onStatusChange?.({
          stage: "error",
          message: "Connection error. Please check your internet connection.",
        });
        resolveOnce({
          success: false,
          error: "WebSocket connection error",
        });
      };

      socket.onclose = (event) => {
        console.log("[NexusSSO] WebSocket closed:", event.code, event.reason);
        if (!resolved) {
          // Only treat as error if we haven't already resolved
          if (event.code !== 1000) {
            onStatusChange?.({
              stage: "error",
              message: "Connection closed unexpectedly",
            });
            resolveOnce({
              success: false,
              error: `Connection closed: ${event.reason || "Unknown reason"}`,
            });
          }
        }
      };
    } catch (error) {
      console.error("[NexusSSO] Error initiating SSO:", error);
      onStatusChange?.({
        stage: "error",
        message: "Failed to start SSO authentication",
      });
      resolveOnce({
        success: false,
        error: `Failed to initiate SSO: ${error}`,
      });
    }
  });
}

/**
 * Cancel an ongoing SSO flow
 * (Useful if user wants to abort)
 */
export function cancelNexusSso(): void {
  // Note: Since we don't expose the socket reference externally,
  // cancellation is handled by the component unmounting or timeout
  console.log("[NexusSSO] SSO cancellation requested");
}
