// https://docs.expo.dev/versions/latest/sdk/filesystem-legacy/
export const documentDirectory: string | null;
export function getInfoAsync(uri: string): Promise<{ exists: boolean; size?: number }>;
export function deleteAsync(uri: string, options?: { idempotent?: boolean }): Promise<void>;
export function makeDirectoryAsync(uri: string, options?: { intermediates?: boolean }): Promise<void>;
export function moveAsync(options: { from: string; to: string }): Promise<void>;
export interface DownloadProgressData { totalBytesWritten: number; totalBytesExpectedToWrite: number }
export interface DownloadResumable { downloadAsync(): Promise<{ uri: string; status: number } | undefined> }
export function createDownloadResumable(uri: string, fileUri: string, options?: Record<string, unknown>,
                                        callback?: (data: DownloadProgressData) => void): DownloadResumable;
