// From docs.cactuscompute.com (React Native, v1.14): CactusLM({ model }), download({ onProgress }),
// init(), complete({ messages, options, tools, onToken }) -> { response, functionCalls }, getModels(), destroy().
// Field names of CactusModel (slug, isDownloaded, sizeMb) are not confirmed by the docs page:
// check them against the installed package's types (npm run typecheck) on first install.
export interface CactusModel {
  slug: string;
  capabilities?: string[];
  quantization?: { int4: { sizeMb: number; url: string }; int8: { sizeMb: number; url: string } };
}
export interface CactusLMTool {
  name: string;
  description: string;
  parameters: { type: "object"; properties: Record<string, { type: string; description: string }>; required: string[] };
}
export interface CactusMessage { role: "system" | "user" | "assistant"; content: string }
export interface CactusCompleteResult {
  success?: boolean;
  response: string;
  functionCalls?: { name: string; arguments: Record<string, unknown> | string }[];
}
export class CactusLM {
  constructor(params?: { model?: string; options?: Record<string, unknown> });
  download(params?: { onProgress?: (progress: number) => void }): Promise<void>;
  init(): Promise<void>;
  complete(params: {
    messages: CactusMessage[];
    options?: { maxTokens?: number; temperature?: number; stopSequences?: string[] };
    tools?: CactusLMTool[];
    onToken?: (token: string) => void;
  }): Promise<CactusCompleteResult>;
  getModels(): Promise<CactusModel[]>;
  stop(): Promise<void>;
  reset(): Promise<void>;
  destroy(): Promise<void>;
}
