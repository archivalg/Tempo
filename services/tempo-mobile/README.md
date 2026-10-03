# tempo-mobile

Tempo's employee app and tablet kiosk (Expo / React Native / TypeScript). Start with [`docs/mobile/README.md`](../../docs/mobile/README.md); verification and gaps are in [`docs/mobile/STATUS.md`](../../docs/mobile/STATUS.md).

```bash
npm ci --legacy-peer-deps
npm run typecheck && npm test
APP_ENV=development npx expo start      # local API on :8017; set EXPO_PUBLIC_API_URL for an emulator or phone
```
`APP_ENV` = `development` | `test` | `production` selects identifiers and the API address (`app.config.ts`). No secrets belong in this app.
