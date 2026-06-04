# Security Policy

## Our commitment

OmniCOVAS handles sensitive local commander context: Elite Dangerous journal data, companion JSON snapshots, settings, API keys, optional authenticated provider data, and future shared-operation state. Security is therefore part of the project architecture, not an afterthought.

The project’s security posture is defined by the current authority family:

- `authority_files/documents/01_core_authority/OmniCOVAS_Master_Blueprint_v5_0_Human_Reference.txt`
- `authority_files/documents/01_core_authority/OmniCOVAS_Master_Blueprint_v5_0_AI_Reference.txt`
- `authority_files/documents/03_backend_source_compliance/OmniCOVAS_Backend_Blueprint_v1_0_Human_Reference.txt`
- `authority_files/documents/03_backend_source_compliance/OmniCOVAS_Backend_Blueprint_v1_0_AI_Reference.txt`
- `authority_files/documents/03_backend_source_compliance/OmniCOVAS_Source_Capability_Routing_Reference_v1.txt`
- `authority_files/documents/03_backend_source_compliance/OmniCOVAS_Compliance_Matrix_v4_1.txt`
- `authority_files/documents/03_backend_source_compliance/OmniCOVAS_Engineering_Standards_v1_0_Human_Reference.md`
- `authority_files/documents/03_backend_source_compliance/OmniCOVAS_Elite_Local_Data_Surface_Reference_v1_0_Human_Reference.md`
- `authority_files/documents/05_adr_decisions/0003-ui-safe-rendering.md`
- `authority_files/documents/05_adr_decisions/ADR_Index.md`

Supporting governance/register files may also be relevant during review:

- `authority_files/documents/04_governance_registers/OmniCOVAS_Source_Verification_Register_v1_0.md` for source/provider claim evidence;
- `authority_files/documents/04_governance_registers/OmniCOVAS_Compliance_Review_Register_v1_0.md` for compliance review evidence and cadence;
- `authority_files/documents/04_governance_registers/OmniCOVAS_Phase_Baseline_Ledger_v1_0.md` for accepted implementation baseline evidence.

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report security issues privately to rocketsprojects.git@gmail.com. Do not open public issues for vulnerabilities.

To report a security issue:

1. Email rocketsprojects.git@gmail.com with a clear security-report subject.
2. Use GitHub Private Vulnerability Reporting only if it is enabled for the official repository.
3. Include, where possible:
   - a clear description of the issue;
   - steps to reproduce;
   - affected commit, version, or branch;
   - expected impact;
   - proof-of-concept details you are comfortable sharing;
   - whether the issue may expose secrets, commander data, local files, external-provider credentials, bridge access, or UI execution paths.

## Response timeline

OmniCOVAS is a zero-budget volunteer project, but security reports are treated seriously.

- **Acknowledgment:** target within 72 hours.
- **Initial assessment:** target within 7 days.
- **Fix development:** as fast as responsibly possible; complex issues may take longer.
- **Coordinated disclosure:** public details are coordinated with the reporter when possible.

## Recognition

Responsible disclosure is appreciated. Reporters may be credited in release notes or a security acknowledgments section unless they prefer to remain anonymous.

OmniCOVAS cannot offer cash bounties.

## Security commitments

OmniCOVAS is designed around these commitments:

- **Local-first by default.** Commander journal data, companion JSON snapshots, state, settings, logs, and local cache remain local unless the commander explicitly enables an outbound flow.
- **No maintainer telemetry.** OmniCOVAS does not report analytics, usage telemetry, or commander data back to project maintainers.
- **Secrets are encrypted at rest.** API keys and provider secrets are stored through the Windows DPAPI-backed vault.
- **Secrets are redacted before logging.** Logs must not contain API keys, tokens, secrets, or credential payloads.
- **Outbound data is opt-in.** External requests require explicit commander control and must be visible in Activity Log.
- **Source routing is bounded.** External providers are used only for supported facts, within respectful project request budgets, with cache/batch behavior before calls.
- **AI is not a fact source.** AI may draft, summarize, classify intent, or prepare a plan; it may not invent facts or bypass source routing.
- **NullProvider must work.** Core functionality must continue when AI is disabled.
- **Confirmation Gate is mandatory.** Protected actions require commander confirmation and audit records.
- **No unattended automation.** OmniCOVAS must not bot, farm, manipulate game memory, bypass the game client, or perform direct AI in-game actions.
- **UI rendering is defensive.** Telemetry, provider data, user input, logs, and WebSocket payloads must not be rendered through unsafe dynamic HTML. Follow ADR 0003.
- **Activity Log is the proof layer.** Meaningful state changes, source chains, external requests, AI drafts, gate decisions, blocked requests, exports, deletes, and diagnostics must be auditable.

## Build signing and distribution (public beta)

OmniCOVAS is currently distributed as a **public beta**. Beta builds are **not code-signed**: there is no Authenticode or installer-signing certificate in this phase. Windows SmartScreen and similar operating-system prompts may warn that the publisher is unverified. Until a signing certificate is in place:

- obtain the build only from the official repository (`https://github.com/RocketsProjects/omnicovas`);
- treat any build obtained elsewhere as untrusted;
- a signed-build posture is planned for a later release and will be reflected here and in the release notes when it lands.

## Prior security remediation

Security alerts surfaced by automated tooling have been triaged and addressed in project history, including:

- `442f8b3` — Address idna and CodeQL security alerts;
- `8eb3f26` — Repair CodeQL HTML parsing test alerts;
- `94ffa9e` — Resolve Dependabot and CodeQL security alerts;
- `4eff435` — record Rust dependency alert triage.

Ongoing dependency and code-scanning alerts are reviewed as part of release hardening.

## In scope

Security reports are welcome for:

- OmniCOVAS source code in this repository;
- the Python backend;
- the Tauri desktop shell;
- the FastAPI bridge and WebSocket event stream;
- local file watchers and parsers;
- Activity Log, source chain, and redaction behavior;
- Windows DPAPI vault behavior;
- settings/privacy/source toggles;
- external request routing, consent, authentication, cache, and rate handling;
- AI provider abstraction and NullProvider behavior;
- Confirmation Gate behavior;
- UI safe rendering, overlay, and bridge-to-renderer paths;
- Tauri/WebView content-security policy, asset loading, and renderer boundary behavior;
- build, dependency, packaging, signing, and release pipeline behavior;
- documentation issues that could cause unsafe implementation.

## Out of scope

The following are generally out of scope for this repository:

- vulnerabilities in Elite Dangerous itself;
- vulnerabilities in third-party providers or services;
- vulnerabilities in operating-system components unrelated to OmniCOVAS use;
- vulnerabilities in user-installed third-party tools or plugins that OmniCOVAS does not bundle;
- social engineering against maintainers or users;
- denial-of-service tests against external community providers.

If an issue crosses a boundary, report it privately and identify the affected project or provider where possible.

## Handling external-provider issues

If a report involves an external API or community provider, OmniCOVAS will:

1. avoid public disclosure until the issue is understood;
2. disable, block, or gate the affected OmniCOVAS integration if needed;
3. coordinate with the provider when appropriate;
4. preserve Activity Log visibility and commander-facing fallback wording;
5. avoid workarounds that violate provider terms, privacy rules, or respectful request budgets.

## Safe-rendering rule

For UI security, follow `authority_files/documents/05_adr_decisions/0003-ui-safe-rendering.md`:

- Prefer `document.createElement` and `textContent` for dynamic values.
- Use project-approved escaping only where explicitly allowed.
- Reject unsafe dynamic `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function`, or string-based timers for untrusted data.

ADR 0003 remains the safe-rendering decision authority unless superseded by a later ADR. `authority_files/documents/05_adr_decisions/ADR_Index.md` tracks ADR lifecycle and supersession status.

## Security review expectations

Security-sensitive pull requests should identify:

- affected data flows;
- applicable Engineering Standards gates;
- local file watcher/parser scope, including any Journal, `Status.json`, companion JSON, synthetic local event, or local-source provenance behavior;
- new or changed outbound behavior;
- secret-handling behavior;
- Activity Log coverage;
- Confirmation Gate coverage;
- privacy/default state;
- UI rendering posture;
- Tauri/WebView content-security-policy or asset-loading impact, where applicable;
- verification commands run.

Thank you for helping keep OmniCOVAS and its commanders safe.


---

Documentation router: use `authority_files/documents/00_index/OmniCOVAS_Index.md` and `authority_files/documents/00_index/OmniCOVAS_Index_AI_Reference.md` to locate the current v5.0 authority documents. The Index is a router only; it does not override the owning authority files.
