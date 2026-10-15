import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, FlatList, KeyboardAvoidingView, Platform, Pressable, Text, TextInput, View } from "react-native";
import { ask, forgetReachability, reachable } from "../router";
import { BrainMode, ChatItem, Settings, store } from "../storage";
import { colors, ui } from "../theme";

type Props = { settings: Settings; saveSettings: (next: Settings) => Promise<void> };

const MODES: { id: BrainMode; label: string }[] = [
  { id: "auto", label: "Auto" },
  { id: "computer", label: "Computer" },
  { id: "phone", label: "Phone" },
];

export default function ChatScreen({ settings, saveSettings }: Props) {
  const [items, setItems] = useState<ChatItem[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [where, setWhere] = useState("Checking...");
  const list = useRef<FlatList<ChatItem>>(null);

  useEffect(() => {
    store.chat().then(setItems);
  }, []);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      if (settings.mode === "phone") {
        setWhere("The phone answers");
        return;
      }
      const target = await reachable(settings).catch(() => null);
      if (!alive) return;
      setWhere(target ? "LOKI on " + target.machine.kind + " (" + target.machine.machine + ")" :
        settings.mode === "computer" ? "Computer not reachable" : "Computer not reachable - the phone answers");
    };
    check();
    const timer = setInterval(check, 30_000);
    return () => { alive = false; clearInterval(timer); };
  }, [settings]);

  const update = (next: ChatItem[]) => {
    setItems(next);
    store.saveChat(next);
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    setBusy(true);
    const user: ChatItem = { id: String(Date.now()), role: "user", text, t: Date.now() };
    const pendingId = user.id + "a";
    let streamed = "";
    let current = [...items, user, { id: pendingId, role: "assistant" as const, text: "...", brain: "", t: Date.now() }];
    setItems(current);
    const answer = await ask(text, items, settings, saveSettings, (token) => {
      streamed += token;
      current = current.map((m) => (m.id === pendingId ? { ...m, text: streamed } : m));
      setItems(current);
    });
    current = current.map((m) => (m.id === pendingId ? { ...m, text: answer.text, brain: answer.brain, error: answer.error } : m));
    update(current);
    setBusy(false);
  };

  return (
    <KeyboardAvoidingView style={ui.screen} behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={90}>
      <View style={[ui.pad, { paddingBottom: 8 }]}>
        <View style={[ui.row, { justifyContent: "space-between" }]}>
          {MODES.map((m) => (
            <Pressable key={m.id} accessibilityRole="button" accessibilityState={{ selected: settings.mode === m.id }}
              onPress={() => { forgetReachability(); saveSettings({ ...settings, mode: m.id }); }}
              style={[ui.quiet, { flex: 1 }, settings.mode === m.id && { borderColor: colors.cyan, backgroundColor: colors.cyanDim }]}>
              <Text style={ui.quietText}>{m.label}</Text>
            </Pressable>
          ))}
        </View>
        <Text style={[ui.dim, { marginTop: 8 }]}>{where}</Text>
      </View>
      <FlatList
        ref={list}
        data={items}
        keyExtractor={(m) => m.id}
        contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 12 }}
        onContentSizeChange={() => list.current?.scrollToEnd({ animated: true })}
        ListEmptyComponent={<Text style={[ui.dim, { marginTop: 40, textAlign: "center" }]}>Ask LOKI anything.</Text>}
        renderItem={({ item }) => (
          <View style={[ui.card, item.role === "user" ? { marginLeft: 48, backgroundColor: colors.panel2 } : { marginRight: 24 },
                        item.error && { borderColor: colors.danger }]}>
            {item.role === "assistant" && item.brain ? <Text style={ui.badge}>{item.brain}</Text> : null}
            <Text style={ui.text} selectable>{item.text}</Text>
          </View>
        )}
      />
      <View style={[ui.row, { padding: 12, borderTopWidth: 1, borderColor: colors.line }]}>
        <TextInput style={[ui.input, { flex: 1, maxHeight: 140 }]} value={draft} onChangeText={setDraft}
          placeholder="Message LOKI" placeholderTextColor={colors.dim} multiline accessibilityLabel="Message" />
        <Pressable accessibilityRole="button" accessibilityLabel="Send" onPress={send} disabled={busy || !draft.trim()}
          style={[ui.button, { minWidth: 72, opacity: busy || !draft.trim() ? 0.5 : 1 }]}>
          {busy ? <ActivityIndicator color={colors.bg} /> : <Text style={ui.buttonText}>Send</Text>}
        </Pressable>
      </View>
      {items.length ? (
        <Pressable onPress={() => update([])} style={{ alignSelf: "center", padding: 8 }} accessibilityRole="button">
          <Text style={ui.dim}>Clear chat</Text>
        </Pressable>
      ) : null}
    </KeyboardAvoidingView>
  );
}
