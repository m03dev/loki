export type SetStateAction<S> = S | ((prev: S) => S);
export type Dispatch<A> = (value: A) => void;
export function useState<S>(initial: S | (() => S)): [S, Dispatch<SetStateAction<S>>];
export function useEffect(effect: () => void | (() => void), deps?: readonly unknown[]): void;
export interface RefObject<T> { current: T | null }
export function useRef<T>(initial: T | null): RefObject<T>;
export type ReactNode = unknown;
