# OmniCOVAS

**Your personal shipboard companion for Elite Dangerous.**

Elite Dangerous offers an entire galaxy of possibilities, but your ship data, plans, discoveries, and useful information can end up scattered across the game and outside tools.

OmniCOVAS brings them together in a Windows command deck. It connects your current session with galactic knowledge, Engineering plans, and the places you've experienced—helping you stay oriented and make more of your time in the cockpit.

**Your journey matters. Your companion should remember it.**

## Explore your command deck

- **Stay aware.** Follow supported ship and session information, from your current location and condition to relevant warnings and events.
- **Plan your builds.** Explore outfitting and Engineering plans, review material requirements, and organize what you need next.
- **Discover galactic intelligence.** Look up useful information about systems, stations, and the wider galaxy, with context for your travels.
- **Remember where you've been.** Your Commander Chronicle brings together recorded visits and personal history, turning familiar places into part of your story.
- **Keep the right information close.** Navigation, objectives, and contextual notifications help you focus on your chosen activity without unnecessary interruptions.

OmniCOVAS is built around connections between these tools. A ship project can lead to a material-gathering journey; that journey can become part of your Commander's history. The long-term goal is a companion that can help a newcomer learn the galaxy and give an experienced pilot meaningful support across exploration, combat, mining, trading, Powerplay, and more.

## How it works

OmniCOVAS runs alongside Elite Dangerous and reads information the game makes available through its local Journal, status, and companion files. Your Commander data stays local by default. Optional external sources and AI assistance are under your control; the core experience does not require an AI provider.

## Getting started

**Windows 10/11 · Build from source**

There is no published installer yet. You can build OmniCOVAS locally for personal use from this repository.

You'll need **Git, Python 3.11, Node.js LTS, Rust with the MSVC toolchain, Microsoft C++ Build Tools, WebView2, and `uv`**.

```powershell
git clone https://github.com/RocketsProjects/OmniCovas.git
cd OmniCovas
uv sync --all-extras --locked
npm.cmd ci
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package/sync_license.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package/build_tauri_sidecar.ps1
npm.cmd run tauri build
```

Launch your local build alongside Elite Dangerous. Start with **Dashboard** for session awareness, explore **Engineering** for your next ship project, and use **Intel**, **Navigation**, and **Operations** as your journey takes shape. Customize optional features in **Settings**.

Local builds are unsigned, so Windows may show a publisher warning.

## Help shape OmniCOVAS

Built by an Elite Dangerous player for fellow Commanders, OmniCOVAS welcomes bug reports, feature ideas, usability feedback, and compatibility findings. [Open an issue](https://github.com/RocketsProjects/OmniCovas/issues) and tell us what would improve your time in the galaxy.

Interested in contributing code? Please read [Contributing](CONTRIBUTING.md) and [contact the maintainer](mailto:rocketsprojects.git@gmail.com) before submitting a patch or pull request; code contributions require prior agreement.

---

OmniCOVAS is free for personal, noncommercial use and **source-available, not open source**. See the [License](LICENSE.md) and [Security Policy](SECURITY.md). It is an independent, unofficial Elite Dangerous companion and is not affiliated with Frontier Developments.
