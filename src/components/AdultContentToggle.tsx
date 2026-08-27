import { Button } from "./ui/button";

/**
 * The 18+ toggle, shared by the library header and the Nexus browser.
 *
 * These were two separate buttons that looked nothing alike — the header used
 * the 18+ glyph with a red outline when adult content was visible, while Browse
 * Nexus used an eye icon with the text "18+"/"SFW". Same decision, two visual
 * languages, so the state of one told you nothing about the other. One component
 * is the only way they stay identical.
 */
export function AdultContentToggle({
  shown,
  onToggle,
  className = "",
}: {
  /** True when adult content is visible. */
  shown: boolean;
  onToggle: () => void;
  className?: string;
}) {
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={onToggle}
      title={
        shown
          ? "Adult content is visible (click to hide)"
          : "Adult content is hidden (click to show)"
      }
      aria-pressed={shown}
      className={`relative px-2 ${className}`}
      // The outline is the whole signal: lit means you are seeing adult content.
      style={shown ? { border: "2px solid #ef4444" } : undefined}
    >
      <img
        src="/icons/18-plus.svg"
        alt="18+"
        className="w-4 h-4"
        style={{ filter: "brightness(0) invert(1)" }}
      />
      {!shown && (
        <span className="absolute inset-0 flex items-center justify-center">
          <span
            className="w-[70%] h-0.5 rotate-[-20deg] rounded-full"
            style={{ backgroundColor: "#ef4444" }}
          />
        </span>
      )}
    </Button>
  );
}
