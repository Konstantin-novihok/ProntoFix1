# Home Master — Android updates from the user's TrueNAS server

## Intended architecture

- GitHub is the source-code repository and development workspace only.
- The running TrueNAS server is the only source of Android update metadata and APK files.
- The Android app checks its configured server at `GET /updates/latest`.
- The APK is downloaded from that same server at `GET /updates/download`.
- The server never checks GitHub Releases and never deploys or restarts itself.
- A GitHub push does not change the running TrueNAS server.
- Server code is updated only when the administrator manually copies the selected source revision, rebuilds/redeploys the container, and starts it.
- A phone update becomes available only after the administrator manually copies a signed APK and its `latest.json` manifest into the server's persistent update directory. Android installation still requires user confirmation.

## Build an Android update (manual GitHub action)

The workflow **Manually build Home Master Android APK** is started only with GitHub → Actions → workflow → Run workflow. It does not run on push and does not create a GitHub Release. It produces an artifact containing both:
- `HomeMaster.apk`
- `latest.json` (the matching version manifest)

The workflow requires persistent signing secrets:
- `KEYSTORE_B64`: base64 of the long-lived release keystore
- `KS_PASS`: keystore password
- `KEY_ALIAS`: optional alias (defaults to `prontofix`)

**Important:** the signing key must match the certificate of the APK already installed on the phones. Do not create a new key until the installed APK signature has been checked. If the old signing key is unavailable, Android will not accept an in-place update; plan a carefully backed-up migration/reinstall instead.

## Publish the phone update on TrueNAS

1. Download the Actions artifact and extract both files, `HomeMaster.apk` and `latest.json`.
2. Find the host directory that is mounted into the running container as `/data`. In the sample TrueNAS YAML this is `/mnt/tank/apps/prontofix/data`; replace `tank` with the actual pool and use the actual host path from your app's volume mapping.
3. Copy both files into the `updates` subdirectory. Example for the sample path:

```sh
sudo mkdir -p /mnt/tank/apps/prontofix/data/updates
sudo cp HomeMaster.apk latest.json /mnt/tank/apps/prontofix/data/updates/
sudo ls -lh /mnt/tank/apps/prontofix/data/updates/
```

Do not put the APK in the source-code directory. The update folder must be persistent and mapped to container `/data`.

The server calculates SHA-256 from its local APK and returns it from `/updates/latest`. The phone receives a relative download path on the same server; no GitHub download URL is used.

## Install on the phone

1. Open Home Master while connected to your server (including through your Tailnet, if that is how you access it).
2. The app checks the server and shows a banner if the server's version is newer.
3. Tap **Скачать обновление**.
4. Save/open the APK and approve Android's package-installer prompt.

Android requires the package name and signing certificate to match and the versionCode to increase. Installation is never silent.

## Server code updates — administrator controlled

A commit or push to GitHub does not change the running TrueNAS server. To update the server, the administrator must manually:
1. Back up the persistent application data and take a TrueNAS snapshot.
2. Copy the selected `server/` and `web/` source files from the chosen GitHub revision to the NAS source directory.
3. Rebuild/redeploy the Docker app using the existing TrueNAS procedure.
4. Verify the service and data after startup.

The Android update endpoint only reads `/data/updates/latest.json` and `/data/updates/HomeMaster.apk`. It has no GitHub integration, deployment trigger, or self-update mechanism.
