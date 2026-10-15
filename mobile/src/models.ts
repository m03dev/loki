// On-phone models: what can be downloaded, how big, how much RAM, what it is good for.
// Sizes are the download sizes on Hugging Face (Q4_K_M GGUF for llama.rn, checked 2026-10);
// Cactus ships its own quantised files, whose sizes it reports itself (getModels()).
// docs/PHONE.md has the same table with sources.
import * as Device from "expo-device";

export type ModelInfo = {
  id: string;
  name: string;
  role: "tools" | "chat";
  sizeMb: number; // approximate download size
  ramGb: number; // phone RAM it is comfortable on
  goodFor: string;
  licence: string;
  source: string;
  cactusSlug?: string; // the name cactus-react-native knows it by (checked against getModels() at run time)
  gguf?: { url: string; file: string }; // for llama.rn
};

const HF = "https://huggingface.co/";

export const MODELS: ModelInfo[] = [
  {
    id: "needle", name: "Needle", role: "tools", sizeMb: 14, ramGb: 1,
    goodFor: "Quick actions on the phone (notes, switching brain, status). Tool calls only, no chat.",
    licence: "Apache-2.0", source: HF + "Cactus-Compute/needle2", cactusSlug: "needle",
  },
  {
    id: "gemma3-270m", name: "Gemma 3 270M", role: "chat", sizeMb: 253, ramGb: 2,
    goodFor: "Tiny and fast; short answers, rewording. Weak at facts and reasoning.",
    licence: "Gemma Terms of Use", source: HF + "google/gemma-3-270m-it", cactusSlug: "gemma3-270m",
    gguf: { url: HF + "unsloth/gemma-3-270m-it-GGUF/resolve/main/gemma-3-270m-it-Q4_K_M.gguf", file: "gemma-3-270m-it-Q4_K_M.gguf" },
  },
  {
    id: "lfm2-350m", name: "LFM2 350M", role: "chat", sizeMb: 229, ramGb: 2,
    goodFor: "Small, quick chat and summaries on older phones.",
    licence: "LFM Open License v1.0", source: HF + "LiquidAI/LFM2-350M", cactusSlug: "lfm2-350m",
    gguf: { url: HF + "LiquidAI/LFM2-350M-GGUF/resolve/main/LFM2-350M-Q4_K_M.gguf", file: "LFM2-350M-Q4_K_M.gguf" },
  },
  {
    id: "smollm2-360m", name: "SmolLM2 360M", role: "chat", sizeMb: 386, ramGb: 2,
    goodFor: "Simple chat (English). llama.rn only.",
    licence: "Apache-2.0", source: HF + "HuggingFaceTB/SmolLM2-360M-Instruct",
    gguf: { url: HF + "HuggingFaceTB/SmolLM2-360M-Instruct-GGUF/resolve/main/smollm2-360m-instruct-q8_0.gguf", file: "smollm2-360m-instruct-q8_0.gguf" },
  },
  {
    id: "qwen3-0.6b", name: "Qwen3 0.6B", role: "chat", sizeMb: 397, ramGb: 3,
    goodFor: "The default: everyday chat, short reasoning, many languages.",
    licence: "Apache-2.0", source: HF + "Qwen/Qwen3-0.6B", cactusSlug: "qwen3-0.6b",
    gguf: { url: HF + "unsloth/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf", file: "Qwen3-0.6B-Q4_K_M.gguf" },
  },
  {
    id: "qwen3-1.7b", name: "Qwen3 1.7B", role: "chat", sizeMb: 1110, ramGb: 6,
    goodFor: "Best answers on a recent phone; slower, uses more battery.",
    licence: "Apache-2.0", source: HF + "Qwen/Qwen3-1.7B", cactusSlug: "qwen3-1.7b",
    gguf: { url: HF + "unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf", file: "Qwen3-1.7B-Q4_K_M.gguf" },
  },
];

export function findModel(id: string): ModelInfo | undefined {
  return MODELS.find((m) => m.id === id);
}

export function phoneRamGb(): number | null {
  const bytes = Device.totalMemory;
  return typeof bytes === "number" && bytes > 0 ? bytes / 1024 ** 3 : null;
}

/** The chat model to suggest for this phone's memory. */
export function recommendedChatModel(ramGb: number | null): string {
  if (ramGb === null) return "qwen3-0.6b";
  if (ramGb >= 7.5) return "qwen3-1.7b";
  if (ramGb >= 3.5) return "qwen3-0.6b";
  return "lfm2-350m";
}

export function formatSize(mb: number): string {
  return mb >= 1000 ? (mb / 1000).toFixed(1) + " GB" : Math.round(mb) + " MB";
}
