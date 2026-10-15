// Cactus (https://github.com/cactus-compute/cactus, npm cactus-react-native): on-device
// inference built for phones. API used, from docs.cactuscompute.com (v1.14 React Native page):
//   new CactusLM({ model })  .download({ onProgress })  .complete({ messages, tools, onToken })
//   -> { response, functionCalls }   .getModels()   .destroy()
// Model slugs are checked against getModels() at run time, so a slug this Cactus version
// does not know shows as "not offered" instead of failing on download.
import { CactusLM } from "cactus-react-native";
import * as FileSystem from "expo-file-system/legacy";
import type { ModelInfo } from "../models";
import { LocalBrain, Message, Tool, ToolCall, stripThinking } from "./LocalBrain";

type Loaded = { slug: string; lm: CactusLM };

export class CactusBrain implements LocalBrain {
  readonly engine = "cactus" as const;
  private loaded: Loaded | null = null;
  private catalog: { slug: string; isDownloaded?: boolean; sizeMb?: number }[] | null = null;

  supports(model: ModelInfo): boolean {
    return Boolean(model.cactusSlug);
  }

  private lm(model: ModelInfo): CactusLM {
    const slug = model.cactusSlug as string;
    if (this.loaded && this.loaded.slug === slug) return this.loaded.lm;
    const lm = new CactusLM({ model: slug });
    return lm;
  }

  /** What this Cactus version offers (slug, downloaded, size), cached for the session. */
  async offered(refresh = false): Promise<{ slug: string; isDownloaded?: boolean; sizeMb?: number }[]> {
    if (this.catalog && !refresh) return this.catalog;
    try {
      const models = await new CactusLM().getModels();
      this.catalog = models.map((m) => ({ slug: m.slug, isDownloaded: m.isDownloaded, sizeMb: m.sizeMb }));
    } catch {
      this.catalog = [];
    }
    return this.catalog;
  }

  async isDownloaded(model: ModelInfo): Promise<boolean> {
    const found = (await this.offered(true)).find((m) => m.slug === model.cactusSlug);
    return Boolean(found && found.isDownloaded);
  }

  async download(model: ModelInfo, onProgress: (progress: number) => void): Promise<void> {
    const offered = await this.offered();
    if (offered.length && !offered.some((m) => m.slug === model.cactusSlug)) {
      throw new Error(model.name + " is not offered by this Cactus version - switch the engine to llama.cpp in Models.");
    }
    await this.lm(model).download({ onProgress });
    this.catalog = null;
  }

  async remove(model: ModelInfo): Promise<void> {
    // Cactus documents no delete call; its files live under the app's documents folder.
    // Remove the folders it is known to use, and say so if none was there.
    if (this.loaded && this.loaded.slug === model.cactusSlug) await this.release();
    const base = FileSystem.documentDirectory || "";
    let removed = false;
    for (const path of [base + "models/" + model.cactusSlug, base + model.cactusSlug, base + "cactus/" + model.cactusSlug]) {
      const info = await FileSystem.getInfoAsync(path);
      if (info.exists) {
        await FileSystem.deleteAsync(path, { idempotent: true });
        removed = true;
      }
    }
    this.catalog = null;
    if (!removed) throw new Error("Could not find " + model.name + "'s files to delete (Cactus keeps them itself). Reinstalling the app removes them.");
  }

  private async ready(model: ModelInfo): Promise<CactusLM> {
    const lm = this.lm(model);
    if (!this.loaded || this.loaded.lm !== lm) {
      await this.release();
      await lm.init();
      this.loaded = { slug: model.cactusSlug as string, lm };
    }
    return lm;
  }

  async chat(model: ModelInfo, messages: Message[], onToken?: (token: string) => void): Promise<string> {
    const lm = await this.ready(model);
    const result = await lm.complete({ messages, onToken, options: { maxTokens: 512, temperature: 0.7 } });
    return stripThinking(result.response || "");
  }

  async callTools(model: ModelInfo, text: string, tools: Tool[]): Promise<ToolCall[]> {
    const lm = await this.ready(model);
    const result = await lm.complete({ messages: [{ role: "user", content: text }], tools, options: { maxTokens: 128, temperature: 0 } });
    return (result.functionCalls || []).map((call) => ({
      name: String(call.name),
      arguments: typeof call.arguments === "string" ? safeJson(call.arguments) : (call.arguments || {}),
    }));
  }

  async release(): Promise<void> {
    const current = this.loaded;
    this.loaded = null;
    if (current) await current.lm.destroy().catch(() => undefined);
  }
}

function safeJson(text: string): Record<string, unknown> {
  try {
    const value = JSON.parse(text);
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}
