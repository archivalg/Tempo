# Building and distributing the Tempo app

Nothing here has been run end to end on a store account. Follow it as a checklist and expect to fix small things on the first pass. **Do not publish publicly**: use TestFlight and Google Play internal testing only.

## 0. Identifiers and accounts (decide first)
| Item | Value / owner |
|---|---|
| iOS bundle id / Android package | proposed `au.com.ensemblesolutions.tempo` (production), `.test`, `.dev`. **Confirm; cannot change after first upload.** |
| Apple | Apple Developer Program membership (organisation). Team ID, App Store Connect app record (name "Tempo" may be taken: have an alternative). |
| Google | Google Play Console organisation account; app record for the package. |
| Expo | An Expo account/organisation; run `eas init` inside `services/tempo-mobile` to get the project id, then set `EAS_PROJECT_ID` (it is not a secret). |
| Push | APNs auth key (.p8) from Apple; Firebase project + FCM v1 service-account JSON. Upload both to Expo (`eas credentials`). The backend needs `TEMPO_PUSH_PROVIDER=expo` (and optionally `TEMPO_EXPO_ACCESS_TOKEN`). |
| API address | `https://tempo.ensemblesolutions.com.au/v1` today; change in `app.config.ts` when the separate API origin exists. |

Never put signing keys, `.p8`/`.p12`/`.jks` files, `google-services.json` or service-account files in the repository (`.gitignore` blocks them). Keep them in EAS credentials or your secret store.

## 1. Local checks (any machine with Node 22)
```bash
cd services/tempo-mobile
npm ci --legacy-peer-deps
npm run typecheck && npm test
APP_ENV=test npm run bundle:android && APP_ENV=test npm run bundle:ios
```

## 2. Android
**Cloud (recommended, no local SDK):**
```bash
npm i -g eas-cli && eas login && eas init
EAS_PROJECT_ID=<id> eas build --platform android --profile test        # installable .apk for testers
EAS_PROJECT_ID=<id> eas build --platform android --profile production  # .aab for Play
```
**Local / CI:** needs JDK 17 and the Android SDK on an x86_64 or Apple-silicon machine (not this arm64 Linux host).
```bash
APP_ENV=test npx expo prebuild --platform android --no-install
cd android && ./gradlew assembleDebug        # app/build/outputs/apk/debug/*.apk (debug-signed, for testing only)
```
The manual GitHub workflow `mobile.yml` → *android-debug-apk* does the same (never run yet).

**Google Play internal testing:** Play Console → Testing → Internal testing → create release → upload the `.aab` (first upload may need Play App Signing enrolment) → add testers (email list) → share the opt-in link. `eas submit -p android --profile production` can upload to the *internal* track as a *draft* (set up a Play service account key first).

## 3. iOS
iOS builds need Apple signing and either EAS (cloud macOS) or a Mac with Xcode.
```bash
EAS_PROJECT_ID=<id> eas build --platform ios --profile test        # internal distribution (ad-hoc; registers tester devices)
EAS_PROJECT_ID=<id> eas build --platform ios --profile production   # for TestFlight
```
EAS creates/manages the distribution certificate, provisioning profile and the push entitlement when you sign in with the Apple account.
**Simulator build (no signing):** on a Mac, `APP_ENV=test npx expo prebuild --platform ios && cd ios && pod install && xcodebuild … -sdk iphonesimulator CODE_SIGNING_ALLOWED=NO` (the manual workflow *ios-simulator-build* does this; never run yet). The simulator cannot receive real push.

**TestFlight:** App Store Connect → your app → TestFlight → after processing, add *internal* testers (members of your App Store Connect team) first; external testing needs a Beta App Review. `eas submit -p ios --profile production` uploads the build (set `ascAppId` in `eas.json`). Answer the export-compliance question (the app uses only standard HTTPS; `ITSAppUsesNonExemptEncryption` is set to false) and complete the App Privacy details from `PRIVACY-INVENTORY.md`.

## 4. Push notifications
1. Create the Expo project (`eas init`) and set `EAS_PROJECT_ID` for builds.
2. Upload the APNs key and the FCM v1 service account to Expo.
3. On the Tempo server set `TEMPO_PUSH_PROVIDER=expo` and `TEMPO_JOBS_ENABLED=true` (the background loop) and restart the backend.
4. On a real phone, install a build, sign in as an invited employee, Settings → *Allow notifications*. Check Administration → *Mobile notifications*: the delivery table separates *accepted by provider*, *provider receipt* and *acknowledged by the phone*.
5. Test: publish a roster that includes that employee; a generic notification should arrive; tapping it must open the shift list.
The simulator/emulator cannot receive remote push; use a physical device.

## 5. Environments
`development` → local API (`http://localhost:8017/v1`; Android emulator uses `10.0.2.2`: override with `EXPO_PUBLIC_API_URL`), `test` → the deployed Tempo environment, `production` → the same host until a separate API origin exists. Each has its own bundle id and URL scheme so builds install side by side.

## 6. Kiosk tablets
Install the **test/production** app, open it, choose *Set up this device as a kiosk*, enter the one-time code from Administration → Kiosk devices. Then lock the tablet to the app at operating-system level (see `KIOSK-SETUP.md`).

## 7. Release checklist (before any external tester)
- [ ] Bundle ids confirmed and registered; accounts in place
- [ ] Designer icon (1024 px) and splash replaced
- [ ] Push credentials uploaded and a real notification received on an iPhone and an Android phone
- [ ] A real tablet of each platform clocked through a full shift cycle, including a deliberately unplugged network
- [ ] Privacy policy URL and support contact live; privacy answers entered from `PRIVACY-INVENTORY.md`
- [ ] Accessibility pass with VoiceOver and TalkBack
- [ ] Rollback understood (below)

## 8. Rollback of the backend/web part of this release
The migration `e7f8a9b0c1d2` is **additive** (new tables, two nullable columns on `shift_assignment`, one on `kiosk_device`); the previous release ignores them. To roll back: redeploy the previous image tags (kept as `tempo-api:rollback-<sha>` and `tempo-tempo_frontend:rollback-<sha>` by the deploy step) with `docker compose -p tempo up -d tempo_backend tempo_frontend`, and leave the schema as is. Only if the new tables must be removed: `alembic downgrade d6e7f8a9b0c1` as the owner role (this **deletes** offers, leave requests, notification and device data) after taking a `pg_dump`.
