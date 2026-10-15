// https://docs.expo.dev/versions/latest/sdk/securestore/
export function getItemAsync(key: string): Promise<string | null>;
export function setItemAsync(key: string, value: string): Promise<void>;
export function deleteItemAsync(key: string): Promise<void>;
