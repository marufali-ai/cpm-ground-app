# CPM Ground Evidence — Android wrapper

A thin Capacitor shell around `../app.html`. The web app itself is unchanged and
still works standalone in a browser — this just packages it as an installable APK
with native camera/GPS permissions.

## INTERIM state (until CloudFront clears)

`capacitor.config.json` has `androidScheme: "http"` and `cleartext: true`, and
`build-www.ps1` defaults to the plain-HTTP EC2 IP. This is because a page served
over HTTPS cannot fetch an `http://` API (blocked as mixed content, independent of
any Android manifest setting) — so both sides have to match while the backend is
still plain HTTP.

**Once CloudFront is live**, switch back to the secure default:
1. `capacitor.config.json` → `"androidScheme": "https"`, remove `"cleartext"`
2. Re-run `.\build-www.ps1 -ApiBase "https://<distribution>.cloudfront.net/api/v1"`
3. Rebuild (see below) — camera/GPS require this secure-context switch to actually
   work on a real device; the interim HTTP build can only be used to test
   login/browsing, not evidence capture.

## Build the APK

```powershell
cd mobile
.\build-www.ps1                      # copies + patches ../app.html into www/index.html
npx cap sync android                 # first time: npx cap add android
cd android
.\gradlew.bat assembleDebug
# output: app\build\outputs\apk\debug\app-debug.apk
```

Install on a connected/USB-debugging phone: `adb install -r app\build\outputs\apk\debug\app-debug.apk`

## Permissions

Camera and location are added to `android/app/src/main/AndroidManifest.xml` after
`cap add android` — see that file for the exact `<uses-permission>` entries. Capacitor
does not prompt for these itself; `app.html`'s own `getUserMedia`/`geolocation` calls
trigger the native runtime permission dialogs the same way they would in Chrome.

## Rebuilding after any app.html change

Just re-run `build-www.ps1` then `npx cap sync android` then the gradle build again —
there's no separate "source" to edit under `mobile/`, `www/index.html` is generated,
not hand-edited.
