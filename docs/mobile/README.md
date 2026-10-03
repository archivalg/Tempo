# Tempo mobile: employee app and tablet kiosk

One real native app for iPhone, Android phones, iPads and Android tablets, in `services/tempo-mobile`. It is not a PWA and not a website in a wrapper: it is React Native, built to native iOS and Android projects.

Read `STATUS.md` first for exactly what has and has not been verified.

## Why this stack
Tempo's console is React + TypeScript and Prime AI's web app is React/Next.js on npm workspaces with Python services; no mobile code exists in either repository (Prime's `apps/android` is an empty placeholder). **Expo (React Native, TypeScript, expo-router)** gives one codebase for iOS and Android in the languages and tooling the team already uses, native secure storage, push notifications, camera and deep links, and a reproducible cloud or local build path. Flutter or two native apps would add a second language and duplicate the logic.

The backend and PostgreSQL database are unchanged in kind: the same FastAPI service, the same roster / attendance / approval rules. The app calls the same server rules the website and kiosk page use; nothing about rosters or attendance is decided in the app.

## What is in the app
* **Employee** (sign in with the username/password the employee chose from an invitation): upcoming published shifts and details (site, local times, overnight and clock-change notes, break, instructions), roster changes, shift offers (accept/decline/confirm again), leave requests with status, availability ("times I cannot work"), clocking history, notification preferences, push registration.
* **Kiosk** (a tablet enrolled by a manager with a one-time code): number + PIN keypad, QR scan of a rotating code from the employee's app, clock in / out and break start / end, an unambiguous result screen, automatic return to the start screen, connectivity indicator, manager sign-in to leave kiosk mode, optional site-location check.
* Employee accounts carry only the `labour.self` permission: they cannot reach any manager screen or endpoint, and see only their own worker record.

## Layout
```
services/tempo-mobile
  app.config.ts        environments (development | test | production), identifiers, plugins, permissions
  eas.json             EAS build profiles (cloud builds)
  app/                 screens (expo-router): (auth) login & invite, (app) tabs, kiosk
  src/api, auth, net, push, kiosk, ui, lib, hooks
  __tests__/           unit and screen tests (jest-expo, Testing Library)
```

## Run, test, build
```bash
cd services/tempo-mobile
npm ci --legacy-peer-deps
npm run typecheck && npm test                       # 38 tests
APP_ENV=development npx expo start                  # needs the local API on :8017 (iOS simulator) or EXPO_PUBLIC_API_URL
APP_ENV=test npm run bundle:android && APP_ENV=test npm run bundle:ios     # JS bundles (proves it compiles for both platforms)
APP_ENV=test npm run prebuild                       # generates the native ios/ and android/ projects (not committed)
```
Environments: `APP_ENV` selects name, identifiers, URL scheme and API address in `app.config.ts`. No secret is ever put in the app: it knows only the public API address. Credentials are typed by the person (session) or entered once by a manager (kiosk device credential) and kept in iOS Keychain / Android Keystore-backed secure storage.

Binary builds (installable app) are in `BUILD-AND-DISTRIBUTION.md`.

## Other documents
* `BUILD-AND-DISTRIBUTION.md` — iOS and Android builds, TestFlight, Google Play internal testing, accounts, identifiers, signing, push set-up
* `EMPLOYEE-ONBOARDING.md` and `KIOSK-SETUP.md` — customer instructions
* `PRIVACY-INVENTORY.md` and `STORE-LISTING-DRAFT.md` — based on what the app actually does
* `STATUS.md` — verification evidence and remaining dependencies
* `docs/timekeeping.md` — attendance rules the kiosk follows
