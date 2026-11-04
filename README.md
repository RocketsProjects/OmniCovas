# OmniCOVAS

A local-first command deck for Elite Dangerous on Windows 10 and Windows 11.
OmniCOVAS brings supported ship and session telemetry, navigation, engineering
plans, recorded visits, galactic knowledge, and commander notes into one desktop
application. Facts retain their source and freshness; missing information remains
unknown. Core workflows work without an AI provider.

This repository contains curated application source and the files needed to build
it. Its `main` branch preserves public history. Source synchronization does not
constitute a software release or release acceptance. There is currently no
published installer or release; build from source for local use.

## Privacy and control

Commander data stays local by default. External providers and outbound features
require explicit opt-in and applicable permissions. Optional AI assists with
explanation and planning; it is not a source of game facts. Protected actions
require commander confirmation. OmniCOVAS does not automate gameplay.

The app is pre-release software. Accessibility coverage is partial; live-game,
fullscreen/overlay, mixed-display, screen-reader, signing, and release acceptance
remain separate verification work.

## Build from source

Requirements: Windows 10/11, Git, Python 3.11, Node.js LTS, Rust with the MSVC
toolchain, Microsoft C++ Build Tools, WebView2, and the `uv` package manager.

```powershell
git clone https://github.com/RocketsProjects/OmniCovas.git
cd OmniCovas
uv sync --all-extras --locked
npm.cmd ci
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package/sync_license.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package/build_tauri_sidecar.ps1
npm.cmd run tauri build
```

For local development, `npm.cmd run tauri dev` starts the desktop shell. Its Python
interpreter is selected from `OMNICOVAS_DEV_PYTHON`, the local `.venv`, `uv`, then
`python` on PATH. The packaged application uses the generated sidecar.

Build output is local and unsigned. Windows SmartScreen may warn about an
unverified publisher. Building an installer does not authorize distributing it.
The test suites and internal verification tooling are maintained in development;
they are not part of this application snapshot.

Some reference datasets are deliberately excluded pending redistribution
clearance. The application handles unavailable references without treating missing
data as verified facts. Shipped galactic knowledge carries its attribution in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Feedback and security

Bug reports and non-code feedback are welcome. Code contributions require prior
written agreement; see [CONTRIBUTING.md](CONTRIBUTING.md) and [CLA.md](CLA.md).
Report vulnerabilities privately to rocketsprojects.git@gmail.com; see
[SECURITY.md](SECURITY.md).

## License and notices

OmniCOVAS is free-to-use source-available proprietary software, not open source.
Personal, noncommercial use, inspection, local builds, and local modifications
are subject to [LICENSE.md](LICENSE.md). Redistribution, publication, rehosting,
repackaging, sublicensing, and commercialization require written permission.
See [NOTICE.md](NOTICE.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Elite Dangerous, Frontier Developments, COVAS, and related marks belong to their
respective owners. OmniCOVAS is an independent, unofficial project and is not
affiliated with or endorsed by Frontier Developments plc.
