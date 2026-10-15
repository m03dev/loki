// llama.rn (https://github.com/mybigday/llama.rn): llama.cpp for React Native, GGUF files.
// The app downloads the GGUF itself (expo-file-system), so size, progress and delete are
// fully under its control. Needle is not a GGUF model: with this engine quick actions are
// skipped and the chat model answers everything.
import * as FileSystem from "expo-file-system/legacy";
import { initLlama, LlamaContext } from "llama.rn";
import { Platform } from "react-native";
import type { ModelInfo } from "../models";
import { LocalBrain, Message, Tool, ToolCall, stripThinking } from "./LocalBrain";

const DIR = (FileSystem.documentDirectory || "") + "models/";

export class LlamaRnBrain implements LocalBrain {
  readonly engine = "llama.rn" as const;
  private loaded: { id: string; ctx: LlamaContext } | null = null;

  supports(model: ModelInfo): boolean {
    return Boolean(model.gguf);
  }

  private path(model: ModelInfo): string {
    return DIR + (model.gguf as { file: string }).file;
  }

  async isDownloaded(model: ModelInfo): Promise<boolean> {
    if (!model.gguf) return false;
    const info = await FileSystem.getInfoAsync(this.path(model));
    return info.exists;
  }

  async download(model: ModelInfo, onProgress: (progress: number) => void): Promise<void> {
    if (!model.gguf) throw new Error(model.name + " has no GGUF file for llama.cpp.");
    await FileSystem.makeDirectoryAsync(DIR, { intermediates: true }).catch(() => undefined);
    const partial = this.path(model) + ".part";
    const job = FileSystem.createDownloadResumable(model.gguf.url, partial, {}, (p) => {
      if (p.totalBytesExpectedToWrite > 0) onProgress(p.totalBytesWritten / p.totalBytesExpectedToWrite);
    });
    const result = await job.downloadAsync();
    if (!result || result.status !== 200) {
      await FileSystem.deleteAsync(partial, { idempotent: true });
      throw new Error("Download failed (HTTP " + (result ? result.status : "?") + ").");
    }
    await FileSystem.moveAsync({ from: partial, to: this.path(model) });
    onProgress(1);
  }

  async remove(model: ModelInfo): Promise<void> {
    if (this.loaded && this.loaded.id === model.id) await this.release();
    if (model.gguf) await FileSystem.deleteAsync(this.path(model), { idempotent: true });
  }

  private async ready(model: ModelInfo): Promise<LlamaContext> {
    if (this.loaded && this.loaded.id === model.id) return this.loaded.ctx;
    await this.release();
    const ctx = await initLlama({
      model: this.path(model),
      n_ctx: 2048,
      n_gpu_layers: Platform.OS === "ios" ? 99 : 0, // Metal on iPhone; CPU on Android
      use_mlock: false,
    });
    this.loaded = { id: model.id, ctx };
    return ctx;
  }

  async chat(model: ModelInfo, messages: Message[], onToken?: (token: string) => void): Promise<string> {
    const ctx = await this.ready(model);
    const result = await ctx.completion({ messages, n_predict: 512, temperature: 0.7 },
      (data) => { if (onToken && data.token) onToken(data.token); });
    return stripThinking(result.text || "");
  }

  async callTools(_model: ModelInfo, _text: string, _tools: Tool[]): Promise<ToolCall[]> {
    return [];
  }

  async release(): Promise<void> {
    const current = this.loaded;
    this.loaded = null;
    if (current) await current.ctx.release().catch(() => undefined);
  }
}
