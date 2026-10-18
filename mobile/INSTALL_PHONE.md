# Put LOKI on your Android phone and iPhone

One app (`mobile/`, Expo / React Native) runs on both. It talks to LOKI on your Mac or PC when it can
reach it, and to a small model on the phone when it cannot. You build it once per phone; after that
it opens like any other app.

**Google AI Studio can't do this.** It only publishes Android apps that it generates itself from a prompt
(to Google Play), not an existing app like LOKI's, and not to Apple's App Store.

You need, on the Mac: **Node 20+** (LOKI already uses it) and, for iPhone, **Xcode** (it's in
/Applications). No Android Studio needed: Android builds in Expo's cloud for free.

Open **Terminal** on the Mac and go to the app once:

```bash
cd ~/Documents/loki/mobile
npm install
npx expo install --fix
```

---

## Android: a cloud build, then install the .apk

1. Make a free account at **https://expo.dev/signup**.
2. In Terminal (still in `mobile`):
   ```bash
   npx eas-cli login
   npx eas-cli build --platform android --profile preview
   ```
   First time it asks to create the project on Expo and an Android keystore: answer **Yes** to both.
   The build takes about 10-20 minutes and ends with a link and a QR code.
3. On the phone, open that link (or scan the QR), download the **.apk** and open it. Android asks
   to allow installs from your browser: allow it once, then **Install**.

Later, for the Play Store: `npx eas-cli build -p android --profile production` makes an .aab;
a Google Play developer account (one-time US$25) and `npx eas-cli submit -p android` upload it.

## iPhone: build from Xcode on the Mac

1. Plug the iPhone into the Mac with a cable, unlock it, tap **Trust**.
2. On the iPhone: **Settings > Privacy & Security > Developer Mode > On** (it restarts).
3. On the Mac: open **Xcode > Settings > Accounts**, press **+** and sign in with your Apple ID.
4. In Terminal (still in `mobile`):
   ```bash
   npx expo prebuild --platform ios
   npx expo run:ios --device --configuration Release
   ```
   Pick your iPhone from the list. If it says a signing team is missing, run `open ios/LOKI.xcworkspace`,
   click **LOKI > Signing & Capabilities**, choose your Apple ID as **Team**, then run the command again.
   If it says the bundle identifier is taken, change `"bundleIdentifier"` in `app.json` to something
   of your own (e.g. `com.yourname.loki`) and run both commands again.
5. On the iPhone: **Settings > General > VPN & Device Management**, tap your Apple ID, **Trust**.

With a free Apple ID the app stops opening after **7 days**: plug in and run step 4 again.
The paid Apple Developer Program (US$99/year) removes that and gives TestFlight and the App Store:
`npx eas-cli build -p ios --profile production`, then `npx eas-cli submit -p ios`.

---

## Pair the phone with LOKI

1. Phone and computer on the same Wi-Fi, LOKI running on the computer.
2. In LOKI on the computer: **Settings > Machines & updates**, the **Phone** card. Tick
   "Let the LOKI phone app talk to this computer", then press **Pair a phone** and give it a name:
   LOKI shows a pairing QR code.
3. In the app: **Connect** tab, scan it. The **Chat** tab now talks to LOKI on your computer.
4. Optional: **Models** tab downloads a small model so the phone answers when the computer is out of reach.

Details: `mobile/README.md` and `docs/PHONE.md`.
