/**
 * Toast deduplication and rate limiting utilities
 */

/**
 * Creates a toast deduplicator that prevents showing duplicate toasts
 * within a specified time window.
 *
 * @param windowMs - Time window in milliseconds to deduplicate toasts (default: 5000ms)
 * @returns Object with shouldShow and clear methods
 */
export function createToastDeduplicator(windowMs: number = 5000) {
  const recentToasts = new Map<string, number>();

  return {
    /**
     * Check if a toast with the given key should be shown
     * @param key - Unique identifier for the toast (e.g., error message)
     * @returns true if toast should be shown, false if it's a duplicate
     */
    shouldShow: (key: string): boolean => {
      const now = Date.now();
      const lastShown = recentToasts.get(key);

      if (lastShown && now - lastShown < windowMs) {
        // Toast was shown recently, skip it
        return false;
      }

      // Mark this toast as shown
      recentToasts.set(key, now);

      // Cleanup old entries to prevent memory leak
      for (const [k, timestamp] of recentToasts.entries()) {
        if (now - timestamp > windowMs * 2) {
          recentToasts.delete(k);
        }
      }

      return true;
    },

    /**
     * Clear all tracked toasts (useful for testing or reset)
     */
    clear: () => recentToasts.clear(),
  };
}

/**
 * Calculate exponential backoff delay
 * @param retryCount - Number of retries so far (0-indexed)
 * @param baseDelayMs - Base delay in milliseconds (default: 5000ms)
 * @param maxDelayMs - Maximum delay in milliseconds (default: 60000ms)
 * @returns Delay in milliseconds
 */
export function calculateBackoff(
  retryCount: number,
  baseDelayMs: number = 5000,
  maxDelayMs: number = 60000
): number {
  const delay = baseDelayMs * Math.pow(2, retryCount);
  return Math.min(delay, maxDelayMs);
}

/**
 * Create a simple hash from a string for deduplication
 * @param str - String to hash
 * @returns Simple numeric hash
 */
export function simpleHash(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash = hash & hash; // Convert to 32-bit integer
  }
  return hash.toString();
}
