# Mobile setup — PWA + Capacitor

The mobile story has two distribution paths:

  1. **PWA** (Progressive Web App): users hit `app.aec-platform.vn` on
     their phone → tap **Cài đặt** in the in-app banner (or browser
     menu) → the site installs to the home screen and runs in
     standalone mode. No app stores involved. Zero install friction
     for "I want to try it" demos and works in regions where Play
     Store / App Store are inconvenient.

  2. **Capacitor native shell**: same web app wrapped as an iOS /
     Android binary that ships through the App Store and Google Play.
     Required when customers demand MDM enrollment, push notifications
     to the system tray, or hardware permissions (camera) that the
     PWA path can't fully unlock on iOS.

Both modes serve the same Next.js build. We avoid bundling drift by
running the native shell in **remote-URL mode** — the WebView simply
loads `https://app.aec-platform.vn`, so a Vercel deploy ships to
mobile instantly without an App Store review cycle.

---

## A. PWA — zero-build, already live

PWA support is **automatically active** on every Vercel deploy. The
moving pieces:

  * `apps/web/public/manifest.webmanifest` — install metadata + icons +
    home-screen shortcuts ("Công việc của tôi", "Tải ảnh công trường").
  * `apps/web/public/sw.js` — service worker. Caches the offline
    fallback + static assets. Never caches authed pages or API.
  * `apps/web/app/offline/page.tsx` — fallback rendered when the SW
    intercepts a failed navigation.
  * `apps/web/components/PwaInstaller.tsx` — registers the SW + shows
    the in-app **Cài đặt** banner (mobile only) when Chrome dispatches
    `beforeinstallprompt`.

### Smoke-test the PWA

1. Open `https://app.aec-platform.vn` on an Android phone in Chrome.
2. After ~30s of use, the **Cài đặt** banner should appear at the
   bottom of the viewport. Tap → Chrome shows the system install
   sheet. Approve.
3. The app icon lands on the home screen. Tap → app opens in
   standalone mode (no Chrome chrome).
4. Open settings → toggle airplane mode → tap any link → the
   `/offline` page renders instead of Chrome's dinosaur.

iOS Safari has a less smooth install path: the user needs to tap
**Share → Add to Home Screen**. We surface this in the future via
a tooltip on the SiteEye photo-upload page (which is the most
mobile-trafficked surface).

---

## B. Capacitor native — App Store + Google Play

### B0. One-time dev environment

```bash
# Xcode 15+ for iOS, Android Studio + JDK 17 for Android
brew install --cask android-studio
xcode-select --install

# Capacitor CLI + iOS/Android adapters
cd apps/web
npm install --save @capacitor/core @capacitor/ios @capacitor/android
npm install --save-dev @capacitor/cli @capacitor/assets
```

### B1. Initialize the native projects (once)

```bash
cd apps/web

# Capacitor needs a `webDir` to exist even in remote-URL mode.
mkdir -p capacitor-shell
echo '<html><body>Loading…</body></html>' > capacitor-shell/index.html

npx cap add ios
npx cap add android
```

This creates `apps/web/ios/` and `apps/web/android/` — both are full
Xcode and Android Studio projects. Check them into git (Capacitor
intentionally treats them as source, not generated artefacts).

### B2. Generate icons + splash from the SVG master

```bash
# Drops 18 sized PNGs into ios/App/App/Assets.xcassets + android/
# /app/src/main/res/* from apps/web/public/icons/icon-512.svg
npx capacitor-assets generate --iconSource public/icons/icon-512.svg
```

### B3. Plugins to wire (avoid App Store rejection)

Apple rejects remote-URL apps that are "essentially a web bookmark"
unless they justify the native shell. Ship at least these plugins:

  * `@capacitor/camera` — used by the SiteEye photo-upload page. The
    PWA camera input works but Capacitor's plugin gives access to the
    higher-resolution sensor + lets us avoid the photo-picker round-trip.
  * `@capacitor/push-notifications` — receive push from the worker
    service. Required so users get RFQ deadline / quota-warning pushes
    when the app is backgrounded. **This alone usually clears the
    "should be a website" rejection.**
  * `@capacitor/preferences` — local key/value for the persisted
    org-switcher choice + last-viewed project (currently a cookie that
    can be cleared by iOS aggressively).

### B4. Build + run

```bash
cd apps/web

# iOS — opens in Xcode. Build + run from there for the simulator;
# for device testing you'll need a paid Apple Developer account + a
# provisioning profile in your team's account.
npx cap sync ios && npx cap open ios

# Android — opens in Android Studio. The emulator works fine for
# anything except camera + push.
npx cap sync android && npx cap open android
```

### B5. Submit to stores

  * **App Store**: register `vn.aecplatform.app` in App Store Connect.
    Use TestFlight for internal beta → 100 testers free with the
    enterprise dev account. Submit for review with screenshots that
    show the SiteEye + Pulse surfaces (not the login screen — the
    review team needs to see the value to clear the remote-URL
    rejection bar).
  * **Google Play**: register the same package name. Internal testing
    track first → open testing for company-wide soft launch →
    production after the first patch cycle.

---

## Update strategy

Because the native shell loads a remote URL, the workflow is:

  * **Content / UI / API changes** — push to `main` → Vercel deploys
    in ~2 min → every native app picks up the new build on the next
    cold-start. **No App Store review.**
  * **Plugin / icon / splash changes** — needs a `npx cap sync` + a
    new IPA / AAB submission. Plan for the 24–48h App Store review
    when scheduling these.

In practice, plugin updates happen quarterly at most. 95% of changes
hit users via the remote-URL path with zero review friction.
