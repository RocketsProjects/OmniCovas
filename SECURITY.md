# Security Policy

Report vulnerabilities privately to **rocketsprojects.git@gmail.com**. Do not
post credentials, commander data, or vulnerability details in public issues.
Include the affected version or commit, reproduction steps using synthetic data,
and the observed impact. Avoid testing against external community services.

OmniCOVAS reads sensitive local game context. Commander data remains local by
default, secrets use Windows DPAPI, logs redact secrets, external providers are
opt-in, and protected actions require commander confirmation. Optional AI must
not replace verified facts or bypass those controls. Core functionality remains
available with AI disabled.

Security reports are welcome for the Python backend, local file handling,
FastAPI/WebSocket bridge, Tauri shell, renderer and content-security policy,
secret storage, privacy and provider controls, dependency and build tooling,
and confirmation/audit behavior. Reports about unrelated third-party services
should go to their owners.

Treat untrusted values as text: use safe DOM construction and avoid dynamic HTML
or code execution for telemetry, provider responses, logs, and user input.

No release or installer has been published. Local builds are unsigned and may
trigger Windows SmartScreen warnings. Only a separately authorized official
release at [RocketsProjects/OmniCovas](https://github.com/RocketsProjects/OmniCovas)
can establish a downloadable distribution. Source synchronization does not imply
release readiness, signing, or security certification.
