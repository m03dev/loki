import { CameraView, useCameraPermissions } from "expo-camera";
import { useEffect, useRef, useState } from "react";
import { Alert, Pressable, ScrollView, Switch, Text, TextInput, View } from "react-native";
import { forget, pairFromCode, probe } from "../machines";
import { forgetReachability } from "../router";
import { Machine, Settings, store } from "../storage";
import { colors, ui } from "../theme";

type Props = { settings: Settings; saveSettings: (next: Settings) => Promise<void> };

export default function ConnectScreen({ settings, saveSettings }: Props) {
  const [machines, setMachines] = useState<Machine[]>([]);
  const [status, setStatus] = useState<Record<string, string>>({});
  const [scanning, setScanning] = useState(false);
  const [code, setCode] = useState("");
  const [note, setNote] = useState("");
  const [permission, requestPermission] = useCameraPermissions();
  const handled = useRef(false);

  const load = async () => setMachines(await store.machines());
  useEffect(() => { load(); }, []);

  const pair = async (text: string) => {
    setNote("Pairing...");
    try {
      const m = await pairFromCode(text);
      forgetReachability();
      setNote(m.lastHost ? "Paired with " + m.machine + " (" + m.kind + ")." :
        "Saved " + m.machine + ", but it did not answer yet. Same Wi-Fi? Phone link on in LOKI?");
      setCode("");
    } catch (err) {
      setNote(err instanceof Error ? err.message : String(err));
    }
    load();
  };

  const startScan = async () => {
    if (!permission || !permission.granted) {
      const answer = await requestPermission();
      if (!answer.granted) { setNote("LOKI needs the camera to scan the code. You can paste the code instead."); return; }
    }
    handled.current = false;
    setScanning(true);
  };

  const test = async (m: Machine) => {
    setStatus((s) => ({ ...s, [m.id]: "Checking..." }));
    try {
      const found = await probe(m);
      setStatus((s) => ({ ...s, [m.id]: found ? "Reachable at " + found.host + (found.status.busy ? " (busy)" : "") : "Not reachable" }));
    } catch (err) {
      setStatus((s) => ({ ...s, [m.id]: err instanceof Error ? err.message : String(err) }));
    }
  };

  const remove = (m: Machine) => {
    Alert.alert("Forget " + m.machine + "?", "The phone will have to pair again.", [
      { text: "Cancel", style: "cancel" },
      { text: "Forget", style: "destructive", onPress: async () => { await forget(m); forgetReachability(); load(); } },
    ]);
  };

  if (scanning) {
    return (
      <View style={ui.screen}>
        <CameraView style={{ flex: 1 }} facing="back" barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
          onBarcodeScanned={({ data }) => {
            if (handled.current) return;
            handled.current = true;
            setScanning(false);
            pair(data);
          }} />
        <Pressable style={[ui.quiet, { margin: 16 }]} onPress={() => setScanning(false)} accessibilityRole="button">
          <Text style={ui.quietText}>Cancel</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <ScrollView style={ui.screen} contentContainerStyle={ui.pad} keyboardShouldPersistTaps="handled">
      <Text style={ui.h1}>Connect to your computer</Text>
      <Text style={[ui.dim, { marginTop: 6 }]}>
        In LOKI on your Mac or PC: Settings &gt; Machines &gt; Phone. Turn it on, press Pair a phone, then scan the code here.
      </Text>
      <Pressable style={[ui.button, { marginTop: 16 }]} onPress={startScan} accessibilityRole="button">
        <Text style={ui.buttonText}>Scan pairing code</Text>
      </Pressable>
      <Text style={ui.h2}>Or paste the code</Text>
      <TextInput style={ui.input} value={code} onChangeText={setCode} placeholder="loki-phone:..." placeholderTextColor={colors.dim}
        autoCapitalize="none" autoCorrect={false} accessibilityLabel="Pairing code" />
      <Pressable style={[ui.quiet, { marginTop: 10 }]} onPress={() => pair(code)} disabled={!code.trim()} accessibilityRole="button">
        <Text style={ui.quietText}>Pair</Text>
      </Pressable>
      {note ? <Text style={[ui.dim, { marginTop: 10 }]}>{note}</Text> : null}

      <Text style={ui.h2}>Your machines</Text>
      {machines.length === 0 ? <Text style={ui.dim}>None yet.</Text> : null}
      {machines.map((m) => (
        <View key={m.id} style={ui.card}>
          <Text style={ui.text}>{m.kind}: {m.machine}{settings.lastGood === m.id ? "  (last used)" : ""}</Text>
          <Text style={ui.dim}>{m.hosts.join(", ")} port {m.port}</Text>
          {status[m.id] ? <Text style={[ui.dim, { color: colors.cyan }]}>{status[m.id]}</Text> : null}
          <View style={[ui.row, { marginTop: 10 }]}>
            <Pressable style={[ui.quiet, { flex: 1 }]} onPress={() => test(m)} accessibilityRole="button"><Text style={ui.quietText}>Test</Text></Pressable>
            <Pressable style={[ui.quiet, { flex: 1 }]} onPress={() => remove(m)} accessibilityRole="button"><Text style={[ui.quietText, { color: colors.danger }]}>Forget</Text></Pressable>
          </View>
        </View>
      ))}

      <Text style={ui.h2}>How LOKI on the computer answers</Text>
      <View style={[ui.card, ui.row, { justifyContent: "space-between" }]}>
        <View style={{ flex: 1 }}>
          <Text style={ui.text}>Let it read my project</Text>
          <Text style={ui.dim}>Plan mode: read-only tools. Off = Ask mode, no tools. The phone can never approve anything.</Text>
        </View>
        <Switch value={settings.planMode} onValueChange={(v) => saveSettings({ ...settings, planMode: v })}
          trackColor={{ true: colors.cyanDim, false: colors.line }} thumbColor={settings.planMode ? colors.cyan : colors.dim} />
      </View>
    </ScrollView>
  );
}
