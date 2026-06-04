# OmniCOVAS

**A local command deck for Elite Dangerous.**

OmniCOVAS is a free-to-use source-available proprietary desktop app for Elite Dangerous commanders. It is not open source.

It is being built to help you keep track of your ship, your current goal, and the useful information around your session without bouncing between game panels, websites, notes, and separate tools.

Elite Dangerous can be a lot to manage. Your ship state, route, cargo, fuel, engineering plans, combat situation, market information, and commander notes can all matter at once. OmniCOVAS exists to bring that context into one local place and make it easier to understand.

OmniCOVAS is now a **public beta — not a v1.0 release**. The local-first command deck is built and integrated across its early development phases, but it is still beta software: expect rough edges, evolving UI, and partial accessibility coverage. The foundation is built carefully: local-first, privacy-conscious, source-labeled, auditable, AI-optional, and commander-controlled.

OmniCOVAS is not a bot, not an autopilot, and not a cloud telemetry service. It does not play the game for you. It does not send your data to the maintainer by default. It does not treat AI guesses as facts.

- **License:** Free-to-use source-available proprietary; not open source
- **Target platform:** Windows 10 / Windows 11
- **Status:** Public beta — not v1.0
- **Accessibility:** Partial coverage; full keyboard / screen-reader certification is deferred to a later certification pass
- **Repository:** `https://github.com/RocketsProjects/omnicovas`

---

## Why this project exists

Elite Dangerous has a huge amount of useful information, but it is scattered.

Some of it is in the game. Some of it is written to local files on your PC. Some of it lives in trusted community tools. Some of it is in your own notes, memory, spreadsheets, bookmarks, or Discord messages.

That works, but it creates friction.

You may be trying to answer simple questions like:

- What is happening to my ship right now?
- What was I doing this session?
- What do I need next?
- Where was I going?
- What did I learn from the last jump, fight, station, or route?
- Which information is fresh, and which information might be old?
- Is this fact from my local game data, a community source, or just unknown?

OmniCOVAS is being built for that gap.

The goal is to become a local command deck that helps commanders see what matters, understand what is known, and decide what to do next.

---

## What OmniCOVAS is

OmniCOVAS is planned as a desktop companion app that reads and organizes information from sources such as:

- the local files Elite Dangerous already writes on your PC;
- live ship and session state where available;
- commander-controlled settings and notes;
- trusted external sources, only when the commander enables them;
- optional AI assistance for explanation, summarizing, planning, and drafting.

The app is designed around a few practical ideas:

- **One place for the current situation.** Your ship, route, goal, warnings, and useful context should be easier to see.
- **Information should show where it came from.** If a fact is local, external, stale, missing, or unsupported, the app should make that clear.
- **The commander stays in control.** OmniCOVAS can suggest, prepare, summarize, or explain. It does not decide for you.
- **AI should be helpful, not magical.** AI is allowed to assist with wording, planning, and understanding. It is not treated as a source of game facts.
- **The app should still work without AI.** Core features should remain useful with AI disabled.

---

## What OmniCOVAS is not

OmniCOVAS is intentionally not trying to be everything.

It is not:

- a bot;
- an autopilot;
- a game memory editor;
- a cheat tool;
- a replacement for player judgment;
- a cloud telemetry service;
- an AI system that invents answers when no source exists;
- a tool that sends your commander data to the maintainer by default.

If OmniCOVAS does not have a verified source for something, it should say so plainly instead of guessing.

---

## Current status

OmniCOVAS is a **public beta — not a v1.0 release**.

The local-first foundation and the early pillar workflows are complete and integrated as **local-only baselines**:

- **Phase 1 — Core**
- **Phase 2 / 2.5 — Ship Telemetry and reconciliation**
- **Phase 3 — UI Shell**
- **Phase 4 — Tactical & Combat / First Operations Bridge** (local-only)
- **Phase 5 — Exploration, Navigation, and source infrastructure** (local-only)
- **Phase 6 — Trade and Mining surfaces** (local-only)
- **Phase 7 — Squadrons local surfaces** (local-only; multi-commander / shared state reserved for a later release)
- **Phase 8 — Engineering planning** (local-only)
- **Phase 9 — Powerplay, BGS, and Campaign Intelligence** (local-only)

The project is currently in **Phase 10 — completion, release hardening, documentation, packaging, and public readiness**. Phase 10 does not add new gameplay features; it audits, documents, hardens, packages, and prepares the project for a public beta.

Accepted phase-baseline evidence is tracked internally in `authority_files/documents/04_governance_registers/OmniCOVAS_Phase_Baseline_Ledger_v1_0.md`; this README keeps only the public summary.

This is beta software. Expect rough edges, evolving UI, developer-focused setup steps, and active refactoring.

- **Accessibility** coverage is partial. Full keyboard and screen-reader certification is deferred to a later certification pass.
- **External community data providers** (EDDN, EDSM, Inara, Spansh, EDAstro, EliteBGS, Ardent, Frontier CAPI, and EDSY/Coriolis references) are **disabled or require authorization by default**. They are only used when you explicitly opt in through a future per-provider activation step.
- **Squadron multi-commander / shared state** remains reserved for a later release; the current Squadrons surfaces are local-only.
- **Installer signing** is not yet in place. See `SECURITY.md` for the unsigned-build note.

---

## What OmniCOVAS is meant to help with

The long-term plan is broad, but it is being built in small verified pieces.

At maturity, OmniCOVAS is intended to help with areas such as:

### Ship awareness

See important ship and session information more clearly: hull, shields, heat, fuel, pips, cargo, modules, loadout, rebuy, and other local telemetry where Elite provides it.

### Combat support

Keep combat-related context in one place: current risk, interdiction and escape events, combat notes, PvP encounter notes, combat zone context, munitions, AX support, and session debriefs.

### Travel and navigation

Track where you are, where you are going, what route information is available, and what information is missing or stale.

### Exploration and exobiology

Support exploration planning, system context, route notes, body information, and future exobiology workflows where reliable sources permit.

### Trading, mining, and carrier planning

Help review possible places to buy or sell goods, mining locations, trade routes, station services, and carrier logistics without pretending old or unsupported data is guaranteed to be correct.

### Engineering and materials

Help track engineering goals, material needs, unlock plans, build references, and related progression work.

### Powerplay, BGS, and group activity

Support future campaign planning, faction context, Powerplay/BGS awareness, squadron coordination, and shared operations while keeping the source of each fact visible.

---

## How the app is organized

OmniCOVAS is designed around a small set of main areas:

- **Dashboard** — what matters right now.
- **Intel** — what is known.
- **Navigation** — where and how to move.
- **Operations** — what you are doing.
- **Activity Log** — what happened and how the app knows.
- **Settings** — how the app behaves.
- **About** — project information, links, credits, and references.

Squadrons (local-only) and Engineering are present as local-only surfaces. Carriers remains reserved for a later release.

---

## Privacy and trust

OmniCOVAS is local-first by default.

That means:

- commander data stays on your machine unless you explicitly enable an outbound feature;
- no telemetry, analytics, or tracking are sent to the project maintainer by default;
- API keys and secrets are stored locally and encrypted using Windows DPAPI;
- secrets are redacted from logs;
- external sources are opt-in and visible through audit surfaces;
- the app should show whether information is local, external, stale, disabled, missing, or unsupported;
- core functionality must remain usable without an AI provider configured.

The goal is not just to show information. The goal is to show information in a way the commander can trust.

---

## AI, voice, and control

AI support is optional.

When enabled, AI is intended to help with things like:

- summarizing what happened;
- explaining available information;
- helping prepare a plan;
- drafting text;
- turning a commander request into a clear next step.

AI is not allowed to become the source of game facts. It must not invent telemetry, prices, station services, route quality, combat risk, or background-simulation information.

Voice and input support are also being designed carefully. OmniCOVAS may support voice features and optional integrations later, but protected actions must remain commander-confirmed and auditable.

No unattended automation. No direct AI-driven in-game action.

---

## Screenshots and demos

Screenshots and demo clips will be added when the app is in a better state to show publicly.

The project is still changing quickly, and the current priority is getting the foundation correct before presenting OmniCOVAS as something ready for everyday use.

---

## Development setup

OmniCOVAS is not yet an end-user release. These commands are for development.

### Requirements

Development target:

- Windows 10 or Windows 11
- Python 3.11
- Rust toolchain via `rustup`
- Node.js LTS
- Microsoft C++ Build Tools
- `uv` Python package manager
- Git
- Elite Dangerous installed for live telemetry testing

Recommended editor:

- Visual Studio Code with Python, Rust Analyzer, Tauri, and Git tooling

### Setup

PowerShell:

```powershell
git clone https://github.com/RocketsProjects/omnicovas.git
cd omnicovas
uv venv --python 3.11
.venv\Scripts\activate
uv sync --all-extras
pre-commit install
```

Recommended local checks:

```powershell
ruff format omnicovas/ tests/
ruff check omnicovas/ tests/
mypy omnicovas/
pytest -v
```

Tauri checks may require Node, Rust, and a correctly configured Windows development environment.

```powershell
npm install
npm run tauri dev
npm run tauri build
```

Use the current phase guide for phase-specific verification commands.

---

## Feedback and Contributions

Bug reports, feature requests, and project feedback are welcome.

Code contributions, pull requests, patches, code snippets, and other technical contributions are not accepted unless separately agreed in writing or expressly accepted by Zakary Peters / RocketsProjects.

Submitting feedback does not grant redistribution, sublicensing, repackaging, commercialization, or publication rights for OmniCOVAS or modified versions.

---

## Internal project documents

OmniCOVAS uses a larger internal document set to keep the project consistent as it grows.

The short version:

- **Master Blueprint** defines the project constitution.
- **UI Blueprint** defines the user-facing app structure.
- **Backend Blueprint** defines services, state, events, APIs, provenance, and privacy enforcement.
- **Source Capability Routing Reference** defines what each source can and cannot support.
- **Compliance Matrix** defines legal, privacy, license, attribution, and external-service constraints.
- **Development Roadmap** defines the Phase 4 through Phase 10 development path.
- **Phase guides and playbooks** turn roadmap work into bounded implementation tasks.
- **Engineering Standards** define canonical implementation patterns, verification expectations, and security-sensitive coding gates.
- **Elite Local Data Surface Reference** defines what local Elite files such as Journal, `Status.json`, and companion JSON snapshots can and cannot prove.
- **Governance/support registers** track phase baseline evidence, source verification evidence, compliance review evidence, ADR lifecycle, and executor alignment review status; they support the owning authorities rather than replacing them.
- **Index** is only a router. It points to the owning document but does not override it.

AI alignment files such as `authority_files/documents/06_executor_alignment/CLAUDE.MD`, `authority_files/documents/06_executor_alignment/CLAUDE_CODE.md`, `authority_files/documents/06_executor_alignment/AGENTS.md`, and `authority_files/documents/06_executor_alignment/GEMINI.md` are used for project development workflows. They define assistant and executor behavior only. They do not override the project blueprints, roadmap, compliance rules, source rules, ADRs, or maintainer instructions.

---

## Support the project

OmniCOVAS is free to use for personal, noncommercial use under its source-available proprietary license.

If you find the project useful, or if you just want to help it keep moving, optional support is appreciated. Any support goes toward practical development costs such as AI usage, testing, build tooling, and project infrastructure.

There are no paid features, no donation-only builds, and no obligation. Testing, feedback, and private bug reports all help too.

<!-- Add support links here when ready, for example:

- GitHub Sponsors: <link>
- Ko-fi: <link>

-->

---

## Security

Please do not report vulnerabilities through public GitHub issues.

Report security issues privately to rocketsprojects.git@gmail.com. Do not open public issues for vulnerabilities. See `SECURITY.md` for details.

Security-sensitive areas include:

- local journal and companion JSON handling;
- secrets and DPAPI vault behavior;
- external API requests and source routing;
- Activity Log redaction and audit behavior;
- Tauri bridge and WebSocket contracts;
- UI safe rendering;
- Confirmation Gate behavior;
- update, packaging, signing, and dependency trust.

---

## License

OmniCOVAS is free-to-use source-available proprietary software. It is not open source.

You may use, inspect, build, and locally modify your own copy for personal, noncommercial use.

You may not redistribute, publish, mirror, rehost, repackage, sublicense, sell, commercialize, or make available OmniCOVAS or any modified version without written permission.

See LICENSE.md for the full license.

For licensing, legal notices, sponsor-preview access, or permission requests, contact rocketsprojects.git@gmail.com.

---

## Acknowledgments

OmniCOVAS is inspired by the Elite Dangerous community tool ecosystem and the commanders who keep that ecosystem alive.

Important community and reference projects include, where applicable and within their terms:

- EDDN
- EDSM
- Inara
- Spansh
- EDAstro
- EliteBGS
- Ardent
- EDMC / EDDiscovery ecosystem references
- EDSY and Coriolis for build-link and format-interoperability concepts

Specific usage, attribution, provider capability, and compliance posture are governed by the project’s Source Capability Routing Reference and Compliance Matrix.

---

## Trademark disclaimer

Elite Dangerous, Frontier Developments, COVAS, and related names, marks, assets, and references are the property of their respective owners.

OmniCOVAS is an independent, unofficial project and is not affiliated with, endorsed by, sponsored by, approved by, or connected to Frontier Developments plc.

OmniCOVAS must not use Frontier-owned assets, traced ship art, screenshots, or copied UI art as project assets unless a future written license explicitly permits it.

---

## Maintainer note

OmniCOVAS is a zero-budget, volunteer-driven project built by a regular Elite Dangerous player who wanted a better command deck.

The project will move slower than a commercial product, but the goal is to build it carefully: local-first, source-labeled, auditable, accessible, and respectful of both commanders and the community tools OmniCOVAS may interact with.
