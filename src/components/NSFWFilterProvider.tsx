import {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from "react";

interface NSFWFilterContextType {
  nsfwBlurEnabled: boolean;
  toggleNsfwBlur: () => void;
}

const NSFWFilterContext = createContext<NSFWFilterContextType | undefined>(
  undefined,
);

const STORAGE_KEY = "nsfwBlurEnabled";

interface NSFWFilterProviderProps {
  children: ReactNode;
}

export function NSFWFilterProvider({ children }: NSFWFilterProviderProps) {
  const [nsfwBlurEnabled, setNsfwBlurEnabled] = useState<boolean>(() => {
    // Default to false (show NSFW content by default, filter off on first start)
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      console.log("[NSFWFilter] Init - localStorage value:", stored);
      if (stored !== null) {
        const parsed = stored === "true";
        console.log("[NSFWFilter] Init - parsed value:", parsed);
        return parsed;
      }
    } catch (e) {
      console.warn("[NSFWFilter] Init - localStorage error:", e);
    }
    console.log("[NSFWFilter] Init - using default: false");
    return false;
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(nsfwBlurEnabled));
    } catch {
      // localStorage not available
    }
  }, [nsfwBlurEnabled]);

  const toggleNsfwBlur = () => {
    console.log(
      "[NSFWFilter] Toggle - current:",
      nsfwBlurEnabled,
      "-> new:",
      !nsfwBlurEnabled,
    );
    setNsfwBlurEnabled((prev) => !prev);
  };

  return (
    <NSFWFilterContext.Provider value={{ nsfwBlurEnabled, toggleNsfwBlur }}>
      {children}
    </NSFWFilterContext.Provider>
  );
}

export function useNsfwFilter(): NSFWFilterContextType {
  const context = useContext(NSFWFilterContext);
  if (context === undefined) {
    throw new Error("useNsfwFilter must be used within a NSFWFilterProvider");
  }
  return context;
}
