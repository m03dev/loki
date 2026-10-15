// Who answers: LOKI on a paired Mac/PC when one is reachable (last good first, 2.5 s per
// try), else the small model on the phone. The switch on the Chat screen can force either.
import { brainFor } from "./brains";
import type { Message } from "./brains/LocalBrain";
import { LinkError, chat as machineChat, probe } from "./machines";
import { MODELS, findModel } from "./models";
import { PHONE_TOOLS, runPhoneTool } from "./phoneTools";
import { ChatItem, Machine, Settings, store } from "./storage";

export type Answer = { text: string; brain: string; error?: boolean };

const REACH_CACHE_MS = 30_000;
let cached: { at: number; machine: Machine; host: string } | null = null;

export function forgetReachability(): void {
  cached = null;
}

/** The machine to use now, or null. Tries the last one that answered first. */
export async function reachable(settings: Settings): Promise<{ machine: Machine; host: string } | null> {
  if (cached && Date.now() - cached.at < REACH_CACHE_MS) return cached;
  const machines = await store.machines();
  const ordered = [...machines].sort((a, b) => (a.id === settings.lastGood ? -1 : b.id === settings.lastGood ? 1 : 0));
  for (const machine of ordered) {
    try {
      const found = await probe(machine);
      if (found) {
        machine.lastHost = found.host;
        machine.lastSeen = Date.now();
        await store.saveMachines(machines);
        cached = { at: Date.now(), machine, host: found.host };
        return cached;
      }
    } catch {
      // reachable but refused (revoked): try the next one
    }
  }
  cached = null;
  return null;
}

function label(machine: Machine): string {
  return machine.kind === "Mac" ? "Mac" : "PC";
}

async function onPhone(text: string, history: ChatItem[], settings: Settings,
                       saveSettings: (next: Settings) => Promise<void>, why: string,
                       onToken?: (t: string) => void): Promise<Answer> {
  const brain = brainFor(settings.engine);
  const needle = findModel("needle");
  if (settings.useNeedle && needle && brain.supports(needle) && await brain.isDownloaded(needle).catch(() => false)) {
    try {
      const calls = await brain.callTools(needle, text, PHONE_TOOLS);
      for (const call of calls) {
        const result = await runPhoneTool(call, settings, saveSettings);
        if (result) return { text: result, brain: "On phone (Needle)" };
      }
    } catch {
      // Needle could not decide: the chat model answers
    }
  }
  const model = findModel(settings.chatModel) || MODELS.find((m) => m.id === "qwen3-0.6b");
  if (!model || !brain.supports(model) || !(await brain.isDownloaded(model).catch(() => false))) {
    return { text: why + "No model on this phone yet: open Models and download one (Qwen3 0.6B is a good start).",
             brain: "On phone", error: true };
  }
  const messages: Message[] = [
    { role: "system", content: "You are LOKI on the user's phone, offline. Answer briefly and plainly. " +
      "If a task needs the user's computer, say it will work when the phone can reach LOKI on the Mac or PC." },
    ...history.slice(-8).filter((m) => !m.error).map((m) => ({ role: m.role, content: m.text } as Message)),
    { role: "user", content: text },
  ];
  const answer = await brain.chat(model, messages, onToken);
  return { text: answer || "(no answer)", brain: "On phone (" + model.name + ")" };
}

export async function ask(text: string, history: ChatItem[], settings: Settings,
                          saveSettings: (next: Settings) => Promise<void>,
                          onToken?: (t: string) => void): Promise<Answer> {
  let why = "";
  if (settings.mode !== "phone") {
    const target = await reachable(settings);
    if (target) {
      try {
        const reply = await machineChat(target.machine, target.host, text, settings.planMode ? "plan" : "ask");
        if (settings.lastGood !== target.machine.id) await saveSettings({ ...settings, lastGood: target.machine.id });
        return { text: reply || "(no answer)", brain: label(target.machine) };
      } catch (err) {
        forgetReachability();
        const status = err instanceof LinkError ? err.status : 0;
        const message = err instanceof Error ? err.message : String(err);
        // Unreachable, busy, or LOKI's model failed: the phone answers. Refused (401/403/429): say so.
        if (settings.mode === "computer" || ![0, 409, 502, 503].includes(status)) {
          return { text: message, brain: label(target.machine), error: true };
        }
        why = label(target.machine) + ": " + message + " - answering on the phone.\n\n";
      }
    } else if (settings.mode === "computer") {
      const machines = await store.machines();
      return { text: machines.length ? "Cannot reach LOKI on your computer. Same Wi-Fi (or Tailscale)? Is the phone link on in LOKI > Settings > Machines?" :
        "No computer paired yet: open Connect and scan the code from LOKI > Settings > Machines > Phone.", brain: "Computer", error: true };
    }
  }
  try {
    const answer = await onPhone(text, history, settings, saveSettings, why, onToken);
    return why && !answer.error ? { ...answer, text: why + answer.text } : answer;
  } catch (err) {
    return { text: why + "The phone's model failed: " + (err instanceof Error ? err.message : String(err)), brain: "On phone", error: true };
  }
}
