import type { CapacitorConfig } from "@capacitor/cli";

/**
 * Capacitor configuration — wraps the deployed Vercel build as a native
 * iOS / Android shell that ships through the App Store and Google Play.
 *
 * Strategy: "remote URL" mode. We do NOT bundle the Next.js build into
 * the native app's assets — that approach (`webDir: 'out'`) needs
 * `next export`, which the Pulse / SiteEye routes can't satisfy
 * because they rely on Server Components + per-request auth cookies.
 *
 * Instead, the native shell points at the production Vercel URL and
 * uses the WKWebView (iOS) / WebView (Android) to load the same HTML
 * that desktop Chrome sees. Updates ship instantly via Vercel — no
 * App Store review cycle for content changes.
 *
 * Trade-offs of remote-URL mode:
 *   + No app review for content changes
 *   + Zero risk of bundle drift vs web
 *   - Cold-start needs a network round-trip (mitigated by the service
 *     worker — once the offline shell is cached, the splash → shell
 *     transition takes ~200ms even on flaky 3G)
 *   - Apple's review team scrutinises remote-URL apps; we need to
 *     ship at least one native plugin (camera, push) to avoid the
 *     "this should be a website" rejection (see mobile/CAPACITOR-SETUP.md)
 */
const config: CapacitorConfig = {
  appId: "vn.aecplatform.app",
  appName: "AEC Platform",
  // `webDir` is required by Capacitor's tooling even in remote-URL mode.
  // Point it at a sentinel directory that the build pipeline populates
  // with a minimal index.html — see scripts/build-capacitor-shell.mjs.
  webDir: "capacitor-shell",
  server: {
    // Production builds load the deployed Vercel URL. Dev / preview
    // builds override this via:
    //   npx cap run ios --livereload --external --url http://10.0.0.5:3000
    url: "https://app.aec-platform.vn",
    cleartext: false,
    // Whitelist of remote origins the WebView is allowed to navigate to.
    // The Vercel domain + the Supabase OAuth callback are critical;
    // without the latter, Google / Microsoft SSO redirects open the
    // system browser instead of staying in the app.
    allowNavigation: [
      "app.aec-platform.vn",
      "*.supabase.co",
      "accounts.google.com",
      "login.microsoftonline.com",
    ],
  },
  ios: {
    contentInset: "automatic",
    // Allow asynchronous, swipe-back gestures so the app feels native
    // even though the content is web. Default `false` makes back-nav
    // require tapping the in-app header arrow only.
    backgroundColor: "#0f172a",
  },
  android: {
    // Force light status bar text on the dark slate-900 chrome.
    backgroundColor: "#0f172a",
    allowMixedContent: false,
  },
  plugins: {
    // Tweak this section as plugins are added — see
    // mobile/CAPACITOR-SETUP.md for the camera + push wiring.
    SplashScreen: {
      launchShowDuration: 1200,
      backgroundColor: "#0f172a",
      androidScaleType: "CENTER_CROP",
    },
  },
};

export default config;
