import type { Engine } from "../storage";
import { CactusBrain } from "./cactus";
import type { LocalBrain } from "./LocalBrain";
import { LlamaRnBrain } from "./llamarn";

const brains: Partial<Record<Engine, LocalBrain>> = {};

/** One brain per engine for the whole app (each keeps one model loaded at a time). */
export function brainFor(engine: Engine): LocalBrain {
  const existing = brains[engine];
  if (existing) return existing;
  const made: LocalBrain = engine === "llama.rn" ? new LlamaRnBrain() : new CactusBrain();
  brains[engine] = made;
  return made;
}

export async function releaseAll(): Promise<void> {
  for (const brain of Object.values(brains)) if (brain) await brain.release();
}
