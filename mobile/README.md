# LOKI phone app (iOS + Android)

**Just want it on your phone? Follow [INSTALL_PHONE.md](INSTALL_PHONE.md).**

One Expo / React Native (TypeScript) app for iPhone and Android. It chats with LOKI on your
Mac or PC when it can reach it over your network, and with a small model on the phone when
it cannot. What it is and how it works: [../docs/PHONE.md](../docs/PHONE.md).

```
App.tsx                    three tabs: Chat, Connect, Models
src/lib/protocol.ts        signing (HMAC-SHA256) + pairing code, no imports (tested from Python)
src/machines.ts            signed requests to LOKI on the computer (engine/phone_link.py)
src/router.ts              who answers: computer (2.5 s probe, last good first) or phone
src/brains/LocalBrain.ts   the on-phone brain interface
src/brains/cactus.ts       Cactus (cactus-react-native): Needle + chat models
src/brains/llamarn.ts      llama.rn (llama.cpp): GGUF chat models
src/models.ts              model catalogue, sizes, RAM-based suggestion (expo-device)
src/phoneTools.ts          Needle's quick actions (notes, which brain) - phone-only
typecheck-stubs/           declarations for an offline typecheck without node_modules
```

## It needs a development build (not Expo Go)

Cactus and llama.rn are native modules, so Expo Go cannot run the app. Build it once:

Prerequisites: Node 20+; for iPhone a Mac with Xcode 16+ and CocoaPods; for Android,
Android Studio (SDK + an emulator or a phone with USB debugging). Then:

```bash
cd mobile
npm install
npx expo install --fix        # aligns expo-* versions with the installed Expo SDK
npm run typecheck             # tsc against the real packages
npx expo prebuild             # writes ios/ and android/ (not committed)
npx expo run:ios --device     # Mac only; pick your iPhone (needs a free Apple ID in Xcode signing)
npx expo run:android --device # Mac or PC; phone with USB debugging on
```

After that, `npm start` (Metro with the dev client) is enough while editing JavaScript;
rebuild only when native packages change.

### Builds without a cable: EAS

```bash
npm install -g eas-cli
eas login
eas build:configure
eas build --profile development --platform android   # installable .apk link
eas build --profile development --platform ios       # needs an Apple Developer account
```

For a standalone build use `--profile preview` (Android .apk) or `production`.

## Checks you can run without a phone

```bash
npm run typecheck:offline     # tsc with typecheck-stubs/ (no npm install needed)
python ../tests/test_phone_link.py   # engine side + this app's protocol.ts in Node 22.6+
```

## Package versions

`package.json` targets **Expo SDK 54** (React Native 0.81, React 19.1). They were chosen
offline: the npm registry was not reachable when this was written, so the first
`npm install` + `npx expo install --fix` decides the exact versions (and the lockfile then
pins them). `cactus-react-native`, `react-native-nitro-modules` and `llama.rn` are set to
`latest`; pin them to what installs. Check after installing:

- `cactus-react-native`: the `CactusLM` calls used are `download({ onProgress })`, `init()`,
  `complete({ messages, options, tools, onToken })` -> `{ response, functionCalls }`,
  `getModels()` and `destroy()` (docs.cactuscompute.com, React Native, v1.14). The field names
  of the model list (`slug`, `isDownloaded`, `sizeMb`) and the slugs other than `qwen3-0.6b`
  were not confirmed; `npm run typecheck` will show any mismatch, and only
  `src/brains/cactus.ts` needs changing.
- Needle: Cactus publishes it as `Cactus-Compute/needle2` / `needle3`. If the installed Cactus
  package does not offer a `needle` slug, the Models screen says so and the chat model
  answers everything.

## Network

Plain HTTP to private addresses only, so the app sets `NSAllowsLocalNetworking` (iOS) and
`usesCleartextTraffic` (Android, via expo-build-properties). iOS asks for "Local Network"
permission the first time; say yes. Every request is signed; see docs/PHONE.md.
