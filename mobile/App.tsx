// LOKI on the phone: chat with LOKI on your Mac/PC when it is reachable, else with a small
// model on the phone. Three screens, no navigation library: Chat, Connect, Models.
import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { AppState, Pressable, Text, View } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { releaseAll } from "./src/brains";
import ChatScreen from "./src/screens/ChatScreen";
import ConnectScreen from "./src/screens/ConnectScreen";
import ModelsScreen from "./src/screens/ModelsScreen";
import { Settings, store } from "./src/storage";
import { colors, ui } from "./src/theme";

type Tab = "chat" | "connect" | "models";
const TABS: { id: Tab; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "connect", label: "Connect" },
  { id: "models", label: "Models" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [settings, setSettings] = useState<Settings | null>(null);

  useEffect(() => {
    store.settings().then(setSettings);
    // Free the model's memory when LOKI goes to the background.
    const sub = AppState.addEventListener("change", (state) => { if (state === "background") releaseAll(); });
    return () => sub.remove();
  }, []);

  const saveSettings = async (next: Settings) => {
    setSettings(next);
    await store.saveSettings(next);
  };

  return (
    <SafeAreaProvider>
      <SafeAreaView style={ui.screen} edges={["top", "bottom"]}>
        <StatusBar style="light" />
        <View style={[ui.row, { paddingHorizontal: 16, paddingVertical: 10 }]}>
          <Text style={[ui.h1, { color: colors.cyan, letterSpacing: 2 }]}>LOKI</Text>
        </View>
        <View style={{ flex: 1 }}>
          {!settings ? null : tab === "chat" ? <ChatScreen settings={settings} saveSettings={saveSettings} /> :
            tab === "connect" ? <ConnectScreen settings={settings} saveSettings={saveSettings} /> :
            <ModelsScreen settings={settings} saveSettings={saveSettings} />}
        </View>
        <View style={[ui.row, { borderTopWidth: 1, borderColor: colors.line, backgroundColor: colors.panel }]}>
          {TABS.map((t) => (
            <Pressable key={t.id} onPress={() => setTab(t.id)} accessibilityRole="tab" accessibilityState={{ selected: tab === t.id }}
              style={{ flex: 1, minHeight: 56, alignItems: "center", justifyContent: "center" }}>
              <Text style={{ color: tab === t.id ? colors.cyan : colors.dim, fontSize: 16, fontWeight: tab === t.id ? "700" : "500" }}>{t.label}</Text>
            </Pressable>
          ))}
        </View>
      </SafeAreaView>
    </SafeAreaProvider>
  );
}
