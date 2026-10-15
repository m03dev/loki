// The on-phone brain behind one small interface, so the runtime can be swapped:
// Cactus (cactus-react-native, also runs Needle) or llama.rn (llama.cpp, GGUF files).
import type { ModelInfo } from "../models";

export type Message = { role: "system" | "user" | "assistant"; content: string };

export type Tool = {
  type: "function";
  function: { name: string; description: string; parameters: Record<string, unknown> };
};

export type ToolCall = { name: string; arguments: Record<string, unknown> };

export interface LocalBrain {
  readonly engine: "cactus" | "llama.rn";
  /** Can this runtime run that model at all? */
  supports(model: ModelInfo): boolean;
  isDownloaded(model: ModelInfo): Promise<boolean>;
  /** progress goes from 0 to 1 */
  download(model: ModelInfo, onProgress: (progress: number) => void): Promise<void>;
  remove(model: ModelInfo): Promise<void>;
  /** A chat answer; onToken gets the text as it is written. */
  chat(model: ModelInfo, messages: Message[], onToken?: (token: string) => void): Promise<string>;
  /** Tool calls for a request (Needle), or [] when no tool fits. */
  callTools(model: ModelInfo, text: string, tools: Tool[]): Promise<ToolCall[]>;
  /** Free the model's memory (the app calls this when it goes to the background). */
  release(): Promise<void>;
}

/** Small models wrap answers in <think>...</think> (Qwen3); the phone shows only the answer. */
export function stripThinking(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>/g, "").replace(/^\s*<think>[\s\S]*$/, "").trim();
}
