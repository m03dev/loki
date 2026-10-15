export namespace JSX {
  type Element = { readonly __jsx: true };
  interface ElementClass { props: unknown }
  interface ElementAttributesProperty { props: {} }
  interface ElementChildrenAttribute { children: {} }
  interface IntrinsicAttributes { key?: string | number; ref?: unknown }
  interface IntrinsicElements {}
}
export function jsx(type: unknown, props: unknown, key?: unknown): JSX.Element;
export function jsxs(type: unknown, props: unknown, key?: unknown): JSX.Element;
export const Fragment: unknown;
