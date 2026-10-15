import { useEffect, useState } from "react";
import { Alert, Pressable, ScrollView, Switch, Text, View } from "react-native";
import { brainFor } from "../brains";
import { MODELS, ModelInfo, formatSize, phoneRamGb, recommendedChatModel } from "../models";
import { Engine, Settings } from "../storage";
import { colors, ui } from "../theme";

type Props = { settings: Settings; saveSettings: (next: Settings) => Promise<void> };

const ENGINES: { id: Engine; label: string }[] = [
  { id: "cactus", label: "Cactus" },
  { id: "llama.rn", label: "llama.cpp" },
];

export default function ModelsScreen({ settings, saveSettings }: Props) {
  const brain = brainFor(settings.engine);
  const [have, setHave] = useState<Record<string, boolean>>({});
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const ram = phoneRamGb();
  const recommended = recommendedChatModel(ram);

  const refresh = async () => {
    const next: Record<string, boolean> = {};
    for (const m of MODELS) next[m.id] = brain.supports(m) ? await brain.isDownloaded(m).catch(() => false) : false;
    setHave(next);
  };
  useEffect(() => { refresh(); }, [settings.engine]);

  const download = async (m: ModelInfo) => {
    setErrors((e) => ({ ...e, [m.id]: "" }));
    setProgress((p) => ({ ...p, [m.id]: 0 }));
    try {
      await brain.download(m, (value) => setProgress((p) => ({ ...p, [m.id]: value })));
    } catch (err) {
      setErrors((e) => ({ ...e, [m.id]: err instanceof Error ? err.message : String(err) }));
    }
    setProgress((p) => { const next = { ...p }; delete next[m.id]; return next; });
    refresh();
  };

  const remove = (m: ModelInfo) => {
    Alert.alert("Delete " + m.name + "?", "Frees about " + formatSize(m.sizeMb) + ".", [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => {
        try { await brain.remove(m); } catch (err) {
          setErrors((e) => ({ ...e, [m.id]: err instanceof Error ? err.message : String(err) }));
        }
        refresh();
      } },
    ]);
  };

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.pad}>
      <Text style={ui.h1}>Models on this phone</Text>
      <Text style={[ui.dim, { marginTop: 6 }]}>
        {ram ? "This phone has " + ram.toFixed(1) + " GB of memory. " : ""}
        Suggested: {MODELS.find((m) => m.id === recommended)?.name} for chat, plus Needle for quick actions.
        They answer when LOKI on your computer cannot be reached.
      </Text>

      <Text style={ui.h2}>Engine</Text>
      <View style={ui.row}>
        {ENGINES.map((e) => (
          <Pressable key={e.id} style={[ui.quiet, { flex: 1 }, settings.engine === e.id && { borderColor: colors.cyan, backgroundColor: colors.cyanDim }]}
            onPress={() => saveSettings({ ...settings, engine: e.id })} accessibilityRole="button">
            <Text style={ui.quietText}>{e.label}</Text>
          </Pressable>
        ))}
      </View>

      {MODELS.map((m) => {
        const supported = brain.supports(m);
        const busy = progress[m.id] !== undefined;
        const isDefault = settings.chatModel === m.id;
        return (
          <View key={m.id} style={[ui.card, { marginTop: 10 }, isDefault && m.role === "chat" && { borderColor: colors.cyan }]}>
            <Text style={ui.text}>
              {m.name}{m.id === recommended ? "  - suggested" : ""}{isDefault && m.role === "chat" ? "  - default" : ""}
            </Text>
            <Text style={ui.dim}>{formatSize(m.sizeMb)} download - needs about {m.ramGb} GB RAM - {m.licence}</Text>
            <Text style={[ui.dim, { marginTop: 4 }]}>{m.goodFor}</Text>
            {!supported ? <Text style={[ui.dim, { marginTop: 6 }]}>Not available with this engine.</Text> : null}
            {busy ? (
              <View style={{ marginTop: 10 }}>
                <View style={{ height: 8, borderRadius: 4, backgroundColor: colors.panel2, flexDirection: "row", overflow: "hidden" }}>
                  <View style={{ flex: progress[m.id] || 0, backgroundColor: colors.cyan }} />
                  <View style={{ flex: 1 - (progress[m.id] || 0) }} />
                </View>
                <Text style={[ui.dim, { marginTop: 4 }]}>Downloading {Math.round((progress[m.id] || 0) * 100)}%</Text>
              </View>
            ) : null}
            {errors[m.id] ? <Text style={[ui.dim, { color: colors.danger, marginTop: 6 }]}>{errors[m.id]}</Text> : null}
            {supported && !busy ? (
              <View style={[ui.row, { marginTop: 10 }]}>
                {have[m.id] ? (
                  <Pressable style={[ui.quiet, { flex: 1 }]} onPress={() => remove(m)} accessibilityRole="button">
                    <Text style={[ui.quietText, { color: colors.danger }]}>Delete</Text>
                  </Pressable>
                ) : (
                  <Pressable style={[ui.button, { flex: 1 }]} onPress={() => download(m)} accessibilityRole="button">
                    <Text style={ui.buttonText}>Download</Text>
                  </Pressable>
                )}
                {m.role === "chat" && !isDefault ? (
                  <Pressable style={[ui.quiet, { flex: 1 }]} onPress={() => saveSettings({ ...settings, chatModel: m.id })} accessibilityRole="button">
                    <Text style={ui.quietText}>Use for chat</Text>
                  </Pressable>
                ) : null}
                {m.role === "tools" ? (
                  <View style={[ui.row, { flex: 1, justifyContent: "flex-end" }]}>
                    <Text style={ui.dim}>Quick actions</Text>
                    <Switch value={settings.useNeedle} onValueChange={(v) => saveSettings({ ...settings, useNeedle: v })}
                      trackColor={{ true: colors.cyanDim, false: colors.line }} thumbColor={settings.useNeedle ? colors.cyan : colors.dim} />
                  </View>
                ) : null}
              </View>
            ) : null}
          </View>
        );
      })}
    </ScrollView>
  );
}
