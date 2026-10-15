// Quick actions Needle can call on the phone. They only touch this app's own data:
// nothing here reaches the computer, so nothing here needs an approval.
import type { Tool, ToolCall } from "./brains/LocalBrain";
import { BrainMode, Settings, store } from "./storage";

export const PHONE_TOOLS: Tool[] = [
  {
    type: "function",
    function: {
      name: "save_note",
      description: "Save a short note or reminder on this phone, to send to LOKI later.",
      parameters: { type: "object", properties: { text: { type: "string", description: "the note" } }, required: ["text"] },
    },
  },
  {
    type: "function",
    function: {
      name: "list_notes",
      description: "Show the notes saved on this phone.",
      parameters: { type: "object", properties: {} },
    },
  },
  {
    type: "function",
    function: {
      name: "use_brain",
      description: "Choose who answers: the computer (Mac or PC), the phone's own model, or automatic.",
      parameters: {
        type: "object",
        properties: { where: { type: "string", enum: ["auto", "computer", "phone"] } },
        required: ["where"],
      },
    },
  },
];

/** Run one tool call; returns the text to show. */
export async function runPhoneTool(call: ToolCall, settings: Settings,
                                   saveSettings: (next: Settings) => Promise<void>): Promise<string | null> {
  if (call.name === "save_note") {
    const text = String(call.arguments.text || "").trim();
    if (!text) return null;
    const notes = await store.notes();
    await store.saveNotes([...notes, text]);
    return "Saved on the phone: “" + text + "” (" + (notes.length + 1) + " notes).";
  }
  if (call.name === "list_notes") {
    const notes = await store.notes();
    return notes.length ? notes.map((n, i) => (i + 1) + ". " + n).join("\n") : "No notes on the phone yet.";
  }
  if (call.name === "use_brain") {
    const where = String(call.arguments.where || "");
    if (!["auto", "computer", "phone"].includes(where)) return null;
    await saveSettings({ ...settings, mode: where as BrainMode });
    return where === "auto" ? "OK - the computer when it is reachable, else the phone." :
      where === "computer" ? "OK - only LOKI on the computer answers now." : "OK - the phone's own model answers now.";
  }
  return null;
}
