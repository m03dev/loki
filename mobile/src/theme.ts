// Dark navy and cyan, like the desktop app. Big touch targets (at least 48 pt).
import { StyleSheet } from "react-native";

export const colors = {
  bg: "#0b1220",
  panel: "#111a2e",
  panel2: "#16223b",
  line: "#22324f",
  text: "#e6edf7",
  dim: "#8ea0bd",
  cyan: "#22d3ee",
  cyanDim: "#0e7490",
  danger: "#f87171",
  ok: "#34d399",
};

export const ui = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  pad: { padding: 16 },
  h1: { color: colors.text, fontSize: 22, fontWeight: "700" },
  h2: { color: colors.text, fontSize: 17, fontWeight: "600", marginTop: 18, marginBottom: 8 },
  text: { color: colors.text, fontSize: 16, lineHeight: 22 },
  dim: { color: colors.dim, fontSize: 14, lineHeight: 20 },
  card: { backgroundColor: colors.panel, borderRadius: 14, padding: 14, marginBottom: 10,
          borderWidth: 1, borderColor: colors.line },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  button: { minHeight: 48, borderRadius: 12, paddingHorizontal: 18, justifyContent: "center",
            alignItems: "center", backgroundColor: colors.cyan },
  buttonText: { color: colors.bg, fontSize: 16, fontWeight: "700" },
  quiet: { minHeight: 48, borderRadius: 12, paddingHorizontal: 16, justifyContent: "center",
           alignItems: "center", backgroundColor: colors.panel2, borderWidth: 1, borderColor: colors.line },
  quietText: { color: colors.text, fontSize: 15, fontWeight: "600" },
  input: { minHeight: 48, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 10, fontSize: 16,
           color: colors.text, backgroundColor: colors.panel2, borderWidth: 1, borderColor: colors.line },
  badge: { alignSelf: "flex-start", borderRadius: 8, paddingHorizontal: 8, paddingVertical: 2,
           backgroundColor: colors.panel2, color: colors.cyan, fontSize: 12, overflow: "hidden", marginBottom: 4 },
});
