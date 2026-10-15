import type { JSX } from "react/jsx-runtime";

type Style = Record<string, unknown> | false | null | undefined | Style[];
type Children = { children?: unknown };
type A11y = { accessibilityRole?: string; accessibilityLabel?: string; accessibilityState?: { selected?: boolean; disabled?: boolean } };

export function View(props: Children & A11y & { style?: Style }): JSX.Element;
export function Text(props: Children & A11y & { style?: Style; selectable?: boolean; numberOfLines?: number }): JSX.Element;
export function TextInput(props: A11y & {
  style?: Style; value?: string; onChangeText?: (text: string) => void; placeholder?: string;
  placeholderTextColor?: string; multiline?: boolean; autoCapitalize?: "none" | "sentences"; autoCorrect?: boolean;
}): JSX.Element;
export function Pressable(props: Children & A11y & { style?: Style; onPress?: () => void; disabled?: boolean }): JSX.Element;
export function ScrollView(props: Children & { style?: Style; contentContainerStyle?: Style; keyboardShouldPersistTaps?: "always" | "handled" | "never" }): JSX.Element;
export function Switch(props: { value: boolean; onValueChange: (value: boolean) => void; trackColor?: { true?: string; false?: string }; thumbColor?: string }): JSX.Element;
export function ActivityIndicator(props: { color?: string; size?: "small" | "large" }): JSX.Element;
export function KeyboardAvoidingView(props: Children & { style?: Style; behavior?: "padding" | "height" | "position"; keyboardVerticalOffset?: number }): JSX.Element;

export interface FlatListProps<T> {
  data: readonly T[];
  keyExtractor: (item: T) => string;
  renderItem: (info: { item: T; index: number }) => JSX.Element | null;
  contentContainerStyle?: Style;
  onContentSizeChange?: (w: number, h: number) => void;
  ListEmptyComponent?: JSX.Element | null;
  ref?: unknown;
}
export class FlatList<T> {
  constructor(props: FlatListProps<T>);
  props: FlatListProps<T>;
  scrollToEnd(options?: { animated?: boolean }): void;
}

export const StyleSheet: { create<T extends Record<string, Record<string, unknown>>>(styles: T): T };
export const Platform: { OS: "ios" | "android" | "web" };
export const Alert: {
  alert(title: string, message?: string,
        buttons?: { text: string; style?: "cancel" | "destructive" | "default"; onPress?: () => void }[]): void;
};
export const AppState: {
  addEventListener(type: "change", listener: (state: "active" | "background" | "inactive") => void): { remove(): void };
};
