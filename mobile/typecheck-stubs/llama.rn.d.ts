// From the llama.rn README (npm llama.rn): initLlama, context.completion(params, onToken), release().
export interface LlamaContext {
  completion(params: {
    prompt?: string;
    messages?: { role: string; content: string }[];
    n_predict?: number;
    temperature?: number;
    stop?: string[];
  }, onToken?: (data: { token: string }) => void): Promise<{ text: string; timings?: unknown }>;
  release(): Promise<void>;
}
export function initLlama(params: { model: string; n_ctx?: number; n_gpu_layers?: number; use_mlock?: boolean }): Promise<LlamaContext>;
