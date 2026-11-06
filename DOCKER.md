# Running AudioCleaner in Docker

The container runs AudioCleaner's **headless CLI mode** (no GUI, no display needed), with `mkvmerge` and `mediainfo` already installed. It's aimed at Linux servers, NAS boxes and Radarr/Sonarr setups.

## Quick start

Always do a dry run first. It reports what would change and touches nothing:

```bash
docker run --rm \
  --user 1000:1000 \
  -v /path/to/media:/media \
  -v ./config:/config \
  ghcr.io/quinnuk/audiocleaner:latest scan /media --dry-run
```

Then run it for real:

```bash
docker run --rm --user 1000:1000 -v /path/to/media:/media -v ./config:/config \
  ghcr.io/quinnuk/audiocleaner:latest scan /media
```

## Watch mode (docker compose)

Copy `docker-compose.example.yml` to `docker-compose.yml`, edit the paths and `user:`, then:

```bash
docker compose up -d
docker compose logs -f
```

## Notes

- **Ownership:** set `--user` / `user:` to the user that owns your media (run `id` on the host). Otherwise replaced files will be owned by root.
- **Read-write mount:** the library must not be mounted `:ro`. AudioCleaner writes a temporary `name.ac_tmp.mkv` next to each original, so you need free space for one extra copy of the largest file.
- **Options:** every CLI flag works after `scan`, e.g. `--languages eng,jpn`, `--keep-commentary`, `--max-safety-mode`. Run `scan --help` for the full list.
- **/config:** this is `$HOME` inside the container, for app-level data such as the processing history.

## Building the image yourself

```bash
git clone https://github.com/quinnuk/audiocleaner.git
cd audiocleaner
docker build -t audiocleaner .
```