"use client";

import { useEffect, useState } from "react";


type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};


/**
 * PWA glue component, mounted once in the root layout:
 *
 *  1. Registers `/sw.js` (the service worker) on every page load in
 *     production. We skip registration in dev because the SW would
 *     cache the HMR client and break hot reload. The registration is
 *     idempotent — calling it again with the same URL is a no-op.
 *
 *  2. Listens for Chrome / Android's `beforeinstallprompt` event and
 *     parks the deferred prompt so we can fire it from a user gesture
 *     later (browsers no longer auto-prompt). When the user clicks the
 *     in-app "Cài app" CTA, we replay the stored event.
 *
 *  3. Hides itself once the user installs (`appinstalled` event) or
 *     dismisses the banner in this session.
 *
 * The banner stays visible only on phone-sized screens — desktop users
 * already get a browser-native install icon in the URL bar and the
 * banner would be noise.
 */
export function PwaInstaller() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    // --- 1. Register the service worker (prod only) ---
    if (
      typeof window !== "undefined" &&
      "serviceWorker" in navigator &&
      process.env.NODE_ENV === "production"
    ) {
      window.addEventListener("load", () => {
        navigator.serviceWorker
          .register("/sw.js", { scope: "/" })
          .catch((err) => {
            // SW registration failure isn't fatal — the app still works
            // online. Log + move on so we don't show users a scary
            // overlay over a noop they can't fix.
            console.warn("[pwa] sw register failed", err);
          });
      });
    }

    // --- 2. Capture the install prompt ---
    const onBefore = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => {
      setDeferred(null);
      setHidden(true);
    };

    window.addEventListener("beforeinstallprompt", onBefore);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBefore);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (!deferred || hidden) return null;

  async function onInstall() {
    if (!deferred) return;
    deferred.prompt();
    const result = await deferred.userChoice;
    if (result.outcome === "accepted") {
      // appinstalled will clear; bias the UI now for snappier feedback.
      setDeferred(null);
    }
    // Either way, dismiss in this session — re-prompting is annoying.
    setHidden(true);
  }

  return (
    <div className="fixed bottom-4 left-1/2 z-50 w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 rounded-lg border border-slate-200 bg-white p-3 shadow-lg sm:hidden">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-blue-600 text-sm font-bold text-white">
          AEC
        </div>
        <div className="flex-1 text-xs">
          <p className="font-medium text-slate-900">Cài AEC Platform về máy</p>
          <p className="mt-0.5 text-slate-600">
            Mở nhanh từ màn hình chính. Hoạt động cả khi mạng yếu.
          </p>
        </div>
      </div>
      <div className="mt-2.5 flex justify-end gap-2">
        <button
          type="button"
          onClick={() => setHidden(true)}
          className="rounded-md px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-100"
        >
          Để sau
        </button>
        <button
          type="button"
          onClick={onInstall}
          className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-blue-700"
        >
          Cài đặt
        </button>
      </div>
    </div>
  );
}
