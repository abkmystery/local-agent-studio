export {};

declare global {
  interface Window {
    localStudio?: {
      apiBase: string;
      token: string;
      platform: string;
    };
  }
}
