# AudioCleaner — Browser GUI in Docker

This is a separate browser-accessible desktop build of AudioCleaner. It runs the **existing PySide6 GUI** inside LinuxServer's KasmVNC desktop and streams that desktop to a web browser.

The existing headless CLI image and `docker-compose.example.yml` are unchanged. Use the CLI image for headless scans; use this GUI image when you want to operate AudioCleaner from a browser.

## What is included

- Existing AudioCleaner GUI and the same scan / select / remux / verify pipeline.
- MKVToolNix (`mkvmerge`) and MediaInfo installed in the container.
- Browser access through KasmVNC on port `3000`.
- Persistent GUI settings, processing history, and diagnostics under `/config`.
- The media library mounted at `/media`.
- Preview Only enabled by default on a first launch.
- A desktop-menu launcher to reopen AudioCleaner if its window is closed.
- The Windows-only startup option is hidden on Linux.

## Requirements

- Docker Engine and the Docker Compose plugin.
- The host media library mounted read-write. AudioCleaner creates a temporary MKV next to the original before it verifies and replaces it, so the selected media folders must be writable and have free space for a temporary copy of the largest file.
- A host group with write access to the media folders. Set `MEDIA_GID` to that group's numeric ID (see Permissions below).

## Quick start

1. Copy this example to `compose.yml`:

   ```bash
   cp docker-compose.gui.example.yml compose.yml
   ```

2. Create a `.env` file in the same directory:

   ```dotenv
   AUDIOCLEANER_USER=quinn
   AUDIOCLEANER_PASSWORD=choose-a-long-password
   MEDIA_GID=1000
   ```

   Change `MEDIA_GID` to the group ID that can write to your media library. Do not publish the web interface directly to the public internet.

3. Make sure the host path in the Compose file is correct. The example maps `/data/media` on the host to `/media` in the container. The existing AudioCleaner folders should then be selected as `/media/movies`, `/media/tv`, or whichever directories you want it to clean.

4. Start the container:

   ```bash
   docker compose -f compose.yml up -d
   docker compose -f compose.yml logs -f
   ```

5. Open `http://SERVER_IP:3000` from a computer on your LAN. KasmVNC will request the username and password from the `.env` file.

## First run and safety

The first launch starts in **Preview Only** mode. Add the media folders and run a manual scan first. Preview Only reports which files would be changed without modifying them.

Watch Mode is different: it processes new files for real after the configured settle period. The GUI therefore asks you to confirm when enabling Watch Mode while Preview Only is selected. Do not enable Watch Mode until you are happy with the preview results and the media-folder permissions.

AudioCleaner only remuxes; it does not re-encode audio or video. It writes and verifies a temporary file before replacing the original. For especially valuable libraries, Maximum Safety Mode can retain a full backup until the post-replacement verification is complete.

## Permissions

The KasmVNC desktop runs as the container's `abc` user. The Compose `group_add` entry adds the host media group as a supplementary group; it does not change ownership of your files.

On the server, inspect the media directory:

```bash
stat -c 'owner=%u group=%g mode=%a path=%n' /data/media
```

Use the numeric group ID that has write permission on the media directories for `MEDIA_GID`. The directory and existing MKV files must grant that group write access. If they do not, adjust the host's media-group permissions deliberately before enabling live processing. Do not recursively change ownership of the whole media library just to make the container start.

The container does not use Docker's `user:` override because the KasmVNC base image needs its own init process to start the desktop and browser services.

## Build the GUI image locally

Before the published GUI image is available, or when testing your own changes, build the image on the server from a checkout of this branch:

```bash
git clone --branch feature/browser-gui-docker https://github.com/quinnuk/audiocleaner.git
cd audiocleaner
docker build -f Dockerfile.gui -t audiocleaner-gui:local .
```

For a local test, change the Compose image name to `audiocleaner-gui:local`. This local build uses the same browser desktop and persistent volume layout; it does not change the existing CLI image.

## Updating

When a new GUI image has been published:

```bash
docker compose -f compose.yml pull
docker compose -f compose.yml up -d
```

Your `./config` folder and media library remain on the host across image updates.

## Security

KasmVNC's built-in username/password is a convenience for LAN access, not a replacement for a properly secured internet-facing gateway. Keep port `3000` on your LAN or behind your VPN / trusted reverse proxy. Do not forward it directly from your router to the public internet.

## Headless CLI remains available

The existing CLI image remains:

```bash
docker run --rm \
  --user 1000:1000 \
  -v /path/to/media:/media \
  -v ./config:/config \
  ghcr.io/quinnuk/audiocleaner:latest scan /media --dry-run
```

See [DOCKER.md](DOCKER.md) for the headless CLI and Watch Mode instructions.
