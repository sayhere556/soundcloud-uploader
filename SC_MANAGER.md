# SC Manager — CLI + web

A release workspace for multiple SoundCloud accounts, with a shared CLI, browser interface and persistent upload queue. The supplied sc.py and src/soundcloud_mcp files remain intact. The new entry point is manager.py. It uses its own account storage and never searches your homelab or imports existing tokens.

## Run in this VS Code Codespace

    python3 -m venv .venv-web
    .venv-web/bin/pip install -r requirements-web.lock
    .venv-web/bin/python manager.py web

In VS Code, forward port 8085 and keep its visibility **Private**. Open the forwarded port in your browser. The default server binds only to loopback.

For a no-credentials demo:

    .venv-web/bin/python manager.py --demo web

Demo mode has three clearly labeled sample accounts and never calls SoundCloud. Click “Try a sample upload” to generate a silent one-second WAV, then add it to the queue. Demo data is separate in .sc-manager-demo; real data uses .sc-manager. Stop the demo before launching the real app on the same port.

## Connect real accounts

1. Create/register a SoundCloud API application at https://soundcloud.com/you/apps.
2. Set SOUNDCLOUD_CLIENT_ID and SOUNDCLOUD_CLIENT_SECRET in Codespace secrets, your process environment, or a private .env in this repository. Do not commit them. .env.web.example lists the new settings, without credentials.
3. Set SCM_REDIRECT_URI to the exact registered callback, normally https://YOUR-CODESPACE-8085.app.github.dev/auth/callback when using the private forwarded Codespace URL. Set SCM_PUBLIC_URL to that same origin without /auth/callback. Restart the app after changes.
4. In Accounts, choose a label (main, alt, label, or your own) and connect through SoundCloud. Authorize each account separately.

The CLI login command starts the same OAuth flow. Keep the web server running to receive its callback. Accounts and tokens are private server-side files, written atomically with a per-account lock for single-use refresh tokens. They are never returned to the browser or included in the Docker image.

## CLI examples

    .venv-web/bin/python manager.py --help
    .venv-web/bin/python manager.py accounts
    .venv-web/bin/python manager.py -a main login
    .venv-web/bin/python manager.py -a main list --limit 50
    .venv-web/bin/python manager.py -a main upload ./mix.wav --cover ./cover.jpg
    .venv-web/bin/python manager.py -a alt upload ./finished-mixes --private
    .venv-web/bin/python manager.py -a label upload ./single.wav --public --at 2026-12-01T19:00:00-06:00
    .venv-web/bin/python manager.py queue
    .venv-web/bin/python manager.py worker
    .venv-web/bin/python manager.py cancel JOB_ID
    .venv-web/bin/python manager.py -a main edit TRACK_URN --title "New title" --sharing public
    .venv-web/bin/python manager.py -a main disconnect --yes

Global flags (--demo, --data-dir and -a) go before the command. Upload commands stage a copy and enqueue work; run worker or keep web running to send it to SoundCloud. Both use the same queue. Private is the default; public uploads and changes take effect on SoundCloud.

## Docker

    docker compose up -d --build

Docker publishes only 127.0.0.1:8085. The service runs as a non-root user. A new named volume holds its own accounts, queue and staged files. It does not mount any host account directory. For CLI access to the same Docker queue:

    docker compose exec sc-manager python manager.py accounts
    docker compose exec sc-manager python manager.py queue

For CLI file uploads in a container, copy only the desired audio/cover files into it with docker compose cp, then use their container paths. Host CLI and Docker use separate data locations unless you deliberately configure shared storage. Never mount an existing token directory without reviewing compatibility.

## Behavior and limits

- WAV/WAVE, FLAC, MP3, AIFF/AIF, M4A and OGG; up to 4 GB per audio file. SoundCloud validates format, duration and account quota.
- Covers: JPG/JPEG/PNG, up to 20 MB. In a web batch, selected metadata and cover apply to all tracks; filenames supply individual titles. Use separate batches for individual covers.
- The browser shows transfer progress to this app. Once queued, it shows waiting/scheduled/uploading/completed status. It does not invent SoundCloud encoding progress.
- Scheduling delays the **upload**, not the publication of an already uploaded track. The app/worker must be running; a due job starts after a stopped workspace resumes.
- Queue history is capped at the newest 200 records in the interface. Track browsing shows the latest 50 by default (CLI supports up to 200 per request).
- Interrupted or uncertain uploads become “needs review.” Check SoundCloud before uploading again; the app never automatically retries a potentially successful upload.
- Successful jobs remove their staged copies. Cancelled/review jobs retain copies for inspection in the data directory. Your source files remain untouched.
- Local token files are protected by filesystem permissions, not encryption. Keep the data directory private. Use only loopback or authenticated private Codespace forwarding. No public hosting or multi-user authentication is configured.
- Disconnect revokes this application’s authorization. It does not delete your tracks. Finish/cancel queued work first.

## Validation

    .venv-web/bin/pip install pytest
    .venv-web/bin/python -m pytest tests_web -q
    node --check sc_manager/static/app.js
    docker compose config --quiet

Tests use temporary directories and mocked SoundCloud responses. No live upload is performed. API implementation reference: https://developers.soundcloud.com/docs/api/guide and https://developers.soundcloud.com/docs/api/explorer/api.json.
