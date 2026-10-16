import { useEffect, useState } from "react";

import { heroIconUrl } from "../lib/api";

/**
 * A hero's square portrait, read from the game itself by the backend; the
 * hero's initials while it loads or when the game has no picture for it.
 */
export function HeroIcon({ avatar, name, className = "h-8 w-8" }: { avatar: string; name: string; className?: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    setFailed(false);
    void heroIconUrl(avatar).then((url) => {
      if (alive) setSrc(url);
    });
    return () => {
      alive = false;
    };
  }, [avatar]);

  if (!src || failed) {
    const initials = name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0]?.toUpperCase())
      .join("");
    return (
      <div
        className={`${className} shrink-0 rounded-md bg-muted flex items-center justify-center text-[10px] font-semibold text-muted-foreground`}
        aria-hidden
      >
        {initials}
      </div>
    );
  }
  return (
    <img
      src={src}
      alt=""
      aria-hidden
      className={`${className} shrink-0 rounded-md object-cover bg-muted`}
      onError={() => setFailed(true)}
    />
  );
}
