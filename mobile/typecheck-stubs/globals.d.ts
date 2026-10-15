// React Native provides these globals (fetch, timers, AbortController).
declare function setTimeout(fn: () => void, ms?: number): number;
declare function clearTimeout(id: number | undefined): void;
declare function setInterval(fn: () => void, ms?: number): number;
declare function clearInterval(id: number | undefined): void;

declare class AbortController {
  readonly signal: AbortSignal;
  abort(): void;
}
interface AbortSignal { readonly aborted: boolean }

interface Response {
  readonly ok: boolean;
  readonly status: number;
  json(): Promise<any>;
  text(): Promise<string>;
}
declare function fetch(url: string, init?: {
  method?: string; headers?: Record<string, string>; body?: string; signal?: AbortSignal;
}): Promise<Response>;
