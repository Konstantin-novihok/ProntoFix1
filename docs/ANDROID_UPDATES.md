# Home Master — Android updates

## What is implemented

- The server exposes `GET /updates/latest`, backed by the public GitHub Releases API.
- Only the latest published stable release with an APK asset is advertised. Drafts and prereleases are not shown.
- The web interface shows an in-app banner when the published release version is newer than the installed native app version.
- The Settings screen has a manual **Проверить обновления** action.
- **Позже** hides the banner for that version on that device; Settings can check again.
- On Android, choosing download uses the existing native **Save as…** flow. After saving, the user opens the APK and confirms installation in Android. The browser version opens the release asset.

No push messages, device identifiers, or per-user update tracking are used. The banner is shown only while the application UI is open or when it becomes visible again.

## Required one-time signing setup

Android accepts an update over an existing installation only when the package ID and signing certificate match, and the update has a non-lower version code. See the Android update rules:
https://developer.android.com/google/play/app-updates

The release workflow intentionally skips publishing until the persistent signing secrets are configured.

1. Obtain the exact keystore that signed the APK currently installed on users' phones. If that key is lost, Android cannot update those installations in place; affected users must uninstall and reinstall, which can erase local app data.
2. Store the keystore outside Git. Create a base64 value, for example on Linux:
   `base64 -w0 release.keystore`
   On Windows PowerShell:
   `[Convert]::ToBase64String([IO.File]::ReadAllBytes("release.keystore"))`
3. In GitHub repository **Settings → Secrets and variables → Actions**, add:
   - `KEYSTORE_B64` — base64 of the persistent keystore
   - `KS_PASS` — keystore password (the build script currently uses the same value for the key password)
   - `KEY_ALIAS` — optional; defaults to `prontofix`
4. Push changes to `main` in `android/`, `server/` or `web/`. The release workflow builds a signed APK with a unique version and publishes a stable GitHub Release. The server picks it up within the cache window (up to five minutes).

**Important signing check:** the existing APK workflow can generate a temporary key when no persistent key is supplied. Such an APK cannot be upgraded by an APK signed with a different key. Do not advertise an update until the installed APK signing certificate has been matched to the release keystore. If the original key was not preserved, plan a controlled one-time reinstall.

## Server deployment

The update endpoint is part of the new server code. Deploy/restart the TrueNAS application using the project's existing deployment procedure so that `server/updates.py` and the updated module list are active. The app banner cannot appear until the running server contains this endpoint.

## Current scope and limitations

- Delivery is an in-app banner only; no Firebase/FCM push notifications.
- A user can dismiss a banner and later re-check from Settings.
- APK download is user initiated. Android's package installer still asks the user to confirm installation; the current UI saves the APK first and the user opens it to continue.
- This workflow publishes an APK release when relevant source paths change on `main`; it does not itself deploy the server container to TrueNAS.
- The first rollout must verify the installed app's signing certificate and package version before distributing updates to existing installs.
