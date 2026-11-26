# SoundCloud uploader

Standalone sc.py CLI with a minimal dark web interface. Upload singles or ordered tapes, import account token JSON or link with SoundCloud, and save visibility and artwork defaults. Covers support no artwork, solid colors, image cropping and color fill at 3000 x 3000.

See [setup and usage](SC_MANAGER.md).

## Project files

- `sc.py`: standalone CLI and web app.
- `sc_manager/`: editable application source and web assets.
- `tools/`: standalone build script.
- `tests_web/`: automated tests; simulated responses stay here.
- `src/soundcloud_mcp/`: preserved original CLI.
- `.env.example`: shared settings template for local and Docker use.

Private account and upload state stays in `.sc-manager/` (or the configured data directory).
