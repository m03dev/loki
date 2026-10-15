import type { JSX } from "react/jsx-runtime";
// https://docs.expo.dev/versions/latest/sdk/camera/
export interface PermissionResponse { granted: boolean; canAskAgain: boolean }
export function useCameraPermissions(): [PermissionResponse | null, () => Promise<PermissionResponse>];
export function CameraView(props: {
  style?: unknown;
  facing?: "front" | "back";
  barcodeScannerSettings?: { barcodeTypes: ("qr" | "pdf417" | "ean13")[] };
  onBarcodeScanned?: (result: { type: string; data: string }) => void;
}): JSX.Element;
