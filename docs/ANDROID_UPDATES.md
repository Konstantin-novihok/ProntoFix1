# Home Master — Android updates from the user's TrueNAS server

## Intended architecture

- GitHub is the source-code repository and development workspace only.
- The running TrueNAS server is the only source of Android update metadata and APK files.
- The Android app checks the configured server at `GET /updates/latest`.
- The APK is downloaded from that same server at `GET /updates/download`.
- The server never checks GitHub Releases and never deploys or restarts itself.
- A server code update happens only when the administrator manually copies the new server files, rebuilds/redeploys the container, and starts it.
- A phone update happens only after the administrator manually places a signed APK and its manifest in the server's persistent update folder. The phone user then chooses Download and confirms installation in Android.

## Publish an Android APK to TrueNAS

The GitHub Actions workflow **Manually build Home Master Android APK** is started only with Actions → workflow → Run workflow. It does not run on push and does not create a GitHub Release. It produces a downloadable artifact named `HomeMaster-APK-...`.

Before running it, configure the persistent signing secrets:
- `KEYSTORE_B64`: base64 of the long-lived release keystore
- `KS_PASS`: keystore password
- `KEY_ALIAS`: optional alias (defaults to `prontofix`)

The signing key must match the certificate of the APK already installed on the phones. Do not create a new key until that has been checked. If the old signing key is unavailable, Android will not accept an in-place update; plan a carefully backed-up migration/reinstall instead.

After downloading the APK artifact from GitHub Actions, copy it to the persistent TrueNAS application data directory:

```sh
mkdir -p /path/to/persistent/app-data/updates
cp HomeMaster.apk /path/to/persistent/app-data/updates/HomeMaster.apk
```

Create `latest.json` beside it (replace the version with the version embedded in the APK):

```json
{
  "version": "3.1.123",
  "name": "Home Master 3.1.123",
  "notes": "Описание изменений"
}
```

The actual mounted path is the host directory mapped to the container's `DATA_DIR` (normally the persistent `data` directory). Keep this folder persistent across container rebuilds. Do not place the APK in the source-code folder.

The server calculates SHA-256 from the local APK and returns it in `/updates/latest`. No GitHub URL is sent to the phone.

## Install on the phone

1. Open Home Master while connected to your server.
2. The app checks the server and shows a banner if the server's version is newer.
3. Tap **Скачать обновление**.
4. Save/open the APK and approve Android's package-installer prompt.

Android requires the package name and signing certificate to match and the versionCode to increase. Installation is never silent.

## Server code updates — administrator controlled

A push or commit to GitHub does not change the running TrueNAS server. To update the server, the administrator must manually:
1. Back up the persistent application data and take a TrueNAS snapshot.
2. Copy the selected `server/` and `web/` source files from the chosen GitHub revision to the NAS source directory.
3. Rebuild/redeploy the Docker app using the existing TrueNAS procedure.
4. Verify the service and data after startup.

The update endpoint only reads local files. It has no GitHub integration, deployment trigger, or self-update mechanism.
