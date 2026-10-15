// What the app remembers. Signing keys go in the phone's keychain/keystore (expo-secure-store);
// everything else (machines without keys, settings, notes, chat) in AsyncStorage.
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";

export type Machine = {
  id: string; // this phone's id on that machine (from the pairing code)
  machine: string; // e.g. "mohameds-mac-mini"
  kind: string; // "Mac" or "PC"
  hosts: string[];
  port: number;
  lastHost?: string;
  lastSeen?: number;
};

export type BrainMode = "auto" | "computer" | "phone";
export type Engine = "cactus" | "llama.rn";

export type Settings = {
  mode: BrainMode;
  engine: Engine;
  chatModel: string; // catalog id of the default on-phone chat model
  useNeedle: boolean; // Needle handles quick on-phone actions when downloaded
  planMode: boolean; // ask LOKI on the computer in Plan (read-only tools) instead of Ask
  lastGood?: string; // machine id that answered last
};

export type ChatItem = { id: string; role: "user" | "assistant"; text: string; brain?: string; error?: boolean; t: number };

const DEFAULTS: Settings = { mode: "auto", engine: "cactus", chatModel: "qwen3-0.6b", useNeedle: true, planMode: false };

async function readJson<T>(key: string, fallback: T): Promise<T> {
  try {
    const raw = await AsyncStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

async function writeJson(key: string, value: unknown): Promise<void> {
  await AsyncStorage.setItem(key, JSON.stringify(value));
}

export const store = {
  async settings(): Promise<Settings> {
    return { ...DEFAULTS, ...(await readJson<Partial<Settings>>("loki.settings", {})) };
  },
  async saveSettings(next: Settings): Promise<void> {
    await writeJson("loki.settings", next);
  },
  async machines(): Promise<Machine[]> {
    return readJson<Machine[]>("loki.machines", []);
  },
  async saveMachines(list: Machine[]): Promise<void> {
    await writeJson("loki.machines", list);
  },
  async key(id: string): Promise<string | null> {
    return SecureStore.getItemAsync("loki.key." + id);
  },
  async saveKey(id: string, key: string): Promise<void> {
    await SecureStore.setItemAsync("loki.key." + id, key);
  },
  async forgetKey(id: string): Promise<void> {
    await SecureStore.deleteItemAsync("loki.key." + id);
  },
  async chat(): Promise<ChatItem[]> {
    return readJson<ChatItem[]>("loki.chat", []);
  },
  async saveChat(items: ChatItem[]): Promise<void> {
    await writeJson("loki.chat", items.slice(-200));
  },
  async notes(): Promise<string[]> {
    return readJson<string[]>("loki.notes", []);
  },
  async saveNotes(notes: string[]): Promise<void> {
    await writeJson("loki.notes", notes.slice(-500));
  },
};
