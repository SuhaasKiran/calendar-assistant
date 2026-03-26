import { useEffect, useState } from "react";

const DEFAULT_ASSISTANT_NAME = "Assistant";
const CONFIG_URL = "/assistant-config.json";
const DEFAULT_ASSISTANT_TAGLINE = "Plan faster. Write smarter. Stay on top of every day.";

type AssistantConfig = {
  assistantName?: unknown;
  assistantTagline?: unknown;
};

type AssistantBrand = {
  assistantName: string;
  assistantTagline: string;
};

let cachedBrand: AssistantBrand | null = null;
let loadPromise: Promise<AssistantBrand> | null = null;

async function loadAssistantBrand(): Promise<AssistantBrand> {
  if (cachedBrand) return cachedBrand;
  if (loadPromise) return loadPromise;

  loadPromise = (async () => {
    try {
      const res = await fetch(CONFIG_URL, { cache: "no-store" });
      if (!res.ok) {
        return {
          assistantName: DEFAULT_ASSISTANT_NAME,
          assistantTagline: DEFAULT_ASSISTANT_TAGLINE,
        };
      }
      const data = (await res.json()) as AssistantConfig;
      const name = typeof data.assistantName === "string" ? data.assistantName.trim() : "";
      const tagline =
        typeof data.assistantTagline === "string" ? data.assistantTagline.trim() : "";
      cachedBrand = {
        assistantName: name || DEFAULT_ASSISTANT_NAME,
        assistantTagline: tagline || DEFAULT_ASSISTANT_TAGLINE,
      };
      return cachedBrand;
    } catch {
      return {
        assistantName: DEFAULT_ASSISTANT_NAME,
        assistantTagline: DEFAULT_ASSISTANT_TAGLINE,
      };
    }
  })();

  return loadPromise;
}

export function useAssistantName(): string {
  const [assistantName, setAssistantName] = useState(
    cachedBrand?.assistantName ?? DEFAULT_ASSISTANT_NAME,
  );

  useEffect(() => {
    void loadAssistantBrand().then((brand) => setAssistantName(brand.assistantName));
  }, []);

  return assistantName;
}


export function useAssistantTagline(): string {
  const [assistantTagline, setAssistantTagline] = useState(
    cachedBrand?.assistantTagline ?? DEFAULT_ASSISTANT_TAGLINE,
  );

  useEffect(() => {
    void loadAssistantBrand().then((brand) => setAssistantTagline(brand.assistantTagline));
  }, []);

  return assistantTagline;
}