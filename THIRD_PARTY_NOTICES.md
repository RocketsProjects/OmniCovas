# Third-Party Notices

OmniCOVAS includes or uses third-party software. Each component remains subject to its own license terms. This record reports dependency metadata and packaging/build-graph evidence; it is not legal advice or a conclusion that every distribution obligation has been discharged.

- **Application version:** 0.1.0
- **Release target:** `x86_64-pc-windows-msvc`
- **Durable machine-readable evidence:** `sbom/` in a prepared release directory and the exact-commit CI artifact named `phase10-candidate-evidence-<commit>`.
- **Source evidence:** installed Python metadata plus PyInstaller analysis, Cargo resolved dependency graphs, and the complete npm lock graph.

## Evidence boundaries

A `packaged-*` Python class means the distribution was mapped from modules in PyInstaller's sidecar analysis. Runtime-closure packages, development tools pulled in by hooks, and implicit/hidden imports are distinguished. This is packaging-analysis evidence, not binary introspection.

`release-runtime-graph` means a Rust package is reachable through normal dependencies in Cargo's resolved graph for the Windows release target. It does not prove that every package or code path remains in the final binary.

Build-only, development-only, declared-but-not-observed, and other-target packages remain in the inventory as conservative legal-review evidence. They are not described as shipped application components. All npm packages are build/test tooling: `package.json` has no runtime dependencies and the UI ships as plain ES modules.

## Inventory summary

The inventory contains **617 components**: **234 release-candidate components** and **383 retained non-release graph components**.

| Ecosystem | Classification | Components |
|---|---|---:|
| npm | development-only | 84 |
| python | build-only | 5 |
| python | declared-runtime-not-observed-in-sidecar | 16 |
| python | development-only | 19 |
| python | packaged-development-tool | 9 |
| python | packaged-runtime | 30 |
| rust | build-only | 70 |
| rust | release-runtime-graph | 195 |
| rust | target-excluded | 189 |

License metadata is present for **617** components; **0** are unknown and **0** are unknown without an explicit allowlisted disposition. Zero unknown metadata is not a legal clearance or an assertion that all obligations are satisfied.

## Qualified review required before publication

A qualified reviewer must determine the applicable obligations for the actual release. This includes MPL-2.0 source/notice obligations and an explicit election for every multi-licensed dependency. This generator records expressions such as `MIT OR Apache-2.0`; it does not make the election.

Metadata expressions containing review keywords in release classes:

| Component | Version | Ecosystem | Evidence class | License |
|---|---|---|---|---|
| `certifi` | 2026.10.23 | python | packaged-runtime | Mozilla Public License 2.0 (MPL 2.0) |
| `cssparser` | 0.37.0 | rust | release-runtime-graph | MPL-2.0 |
| `dtoa-short` | 0.3.5 | rust | release-runtime-graph | MPL-2.0 |
| `option-ext` | 0.2.0 | rust | release-runtime-graph | MPL-2.0 |
| `selectors` | 0.38.0 | rust | release-runtime-graph | MPL-2.0 |

## License-expression summary for release classes

| Metadata expression | Components |
|---|---:|
| MIT OR Apache-2.0 | 99 |
| MIT | 43 |
| Apache-2.0 OR MIT | 24 |
| Unicode-3.0 | 15 |
| BSD-3-Clause | 10 |
| Unlicense OR MIT | 7 |
| MIT License | 4 |
| MIT/Apache-2.0 | 4 |
| MPL-2.0 | 4 |
| BSD License | 2 |
| Apache-2.0 | 2 |
| Unlicense/MIT | 2 |
| Mozilla Public License 2.0 (MPL 2.0) | 1 |
| MIT AND PSF-2.0 | 1 |
| Apache-2.0 OR BSD-2-Clause | 1 |
| BSD-2-Clause | 1 |
| Python Software Foundation License | 1 |
| Apache Software License OR MIT License | 1 |
| PSF-2.0 | 1 |
| Apache Software License | 1 |
| BSD-3-Clause AND MIT | 1 |
| BSD-3-Clause/MIT | 1 |
| Apache-2.0 AND MIT | 1 |
| CC0-1.0 OR MIT-0 OR Apache-2.0 | 1 |
| (Apache-2.0 OR MIT) AND BSD-3-Clause | 1 |
| Apache-2.0 / MIT | 1 |
| Zlib | 1 |
| MIT OR Apache-2.0 OR Zlib | 1 |
| Zlib OR Apache-2.0 OR MIT | 1 |
| (MIT OR Apache-2.0) AND Unicode-3.0 | 1 |

## Release-class components

| Component | Version | Ecosystem | Evidence class | License |
|---|---|---|---|---|
| `aiosqlite` | 0.22.1 | python | packaged-runtime | MIT License |
| `annotated-doc` | 0.0.5 | python | packaged-runtime | MIT |
| `annotated-types` | 0.8.0 | python | packaged-runtime | MIT |
| `anyio` | 4.16.0 | python | packaged-runtime | MIT |
| `ast_serialize` | 0.13.1 | python | packaged-development-tool | MIT |
| `certifi` | 2026.10.23 | python | packaged-runtime | Mozilla Public License 2.0 (MPL 2.0) |
| `click` | 8.5.0 | python | packaged-runtime | BSD-3-Clause |
| `colorama` | 0.4.6 | python | packaged-development-tool | BSD License |
| `fastapi` | 0.162.0 | python | packaged-runtime | MIT |
| `greenlet` | 3.5.6 | python | packaged-runtime | MIT AND PSF-2.0 |
| `h11` | 0.16.0 | python | packaged-runtime | MIT License |
| `httpcore` | 1.0.9 | python | packaged-runtime | BSD-3-Clause |
| `httptools` | 0.9.0 | python | packaged-runtime | MIT |
| `httpx` | 0.28.1 | python | packaged-runtime | BSD License |
| `idna` | 3.20 | python | packaged-runtime | BSD-3-Clause |
| `librt` | 0.16.0 | python | packaged-development-tool | MIT |
| `mypy` | 2.4.1 | python | packaged-development-tool | MIT |
| `mypy_extensions` | 1.2.0 | python | packaged-development-tool | MIT |
| `opentelemetry-api` | 1.45.2 | python | packaged-runtime | Apache-2.0 |
| `packaging` | 26.3 | python | packaged-development-tool | Apache-2.0 OR BSD-2-Clause |
| `psutil` | 7.2.2 | python | packaged-runtime | BSD-3-Clause |
| `pydantic` | 2.14.3 | python | packaged-runtime | MIT |
| `pydantic_core` | 2.50.4 | python | packaged-runtime | MIT |
| `Pygments` | 2.21.0 | python | packaged-development-tool | BSD-2-Clause |
| `pytest` | 9.2.0 | python | packaged-development-tool | MIT |
| `python-dotenv` | 1.2.4 | python | packaged-runtime | BSD-3-Clause |
| `pywin32` | 312 | python | packaged-runtime | Python Software Foundation License |
| `PyYAML` | 6.0.3 | python | packaged-runtime | MIT License |
| `setuptools` | 84.2.1 | python | packaged-development-tool | MIT |
| `sniffio` | 1.3.1 | python | packaged-runtime | Apache Software License OR MIT License |
| `SQLAlchemy` | 2.1.8 | python | packaged-runtime | MIT |
| `starlette` | 1.10.0 | python | packaged-runtime | BSD-3-Clause |
| `structlog` | 26.1.0 | python | packaged-runtime | MIT OR Apache-2.0 |
| `typing-inspection` | 0.4.5 | python | packaged-runtime | MIT |
| `typing_extensions` | 4.16.0 | python | packaged-runtime | PSF-2.0 |
| `uvicorn` | 0.54.0 | python | packaged-runtime | BSD-3-Clause |
| `watchdog` | 6.0.0 | python | packaged-runtime | Apache Software License |
| `watchfiles` | 1.3.0 | python | packaged-runtime | MIT License |
| `websockets` | 17.4 | python | packaged-runtime | BSD-3-Clause |
| `aho-corasick` | 1.1.5 | rust | release-runtime-graph | Unlicense OR MIT |
| `alloc-no-stdlib` | 3.0.0 | rust | release-runtime-graph | BSD-3-Clause |
| `alloc-stdlib` | 0.3.0 | rust | release-runtime-graph | BSD-3-Clause |
| `anyhow` | 1.0.104 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `base64` | 0.23.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `bit-set` | 0.8.0 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `bit-vec` | 0.8.0 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `bitflags` | 1.3.2 | rust | release-runtime-graph | MIT/Apache-2.0 |
| `bitflags` | 2.13.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `brotli` | 9.1.1 | rust | release-runtime-graph | BSD-3-Clause AND MIT |
| `brotli-decompressor` | 6.2.0 | rust | release-runtime-graph | BSD-3-Clause/MIT |
| `bs58` | 0.5.1 | rust | release-runtime-graph | MIT/Apache-2.0 |
| `bytes` | 1.12.1 | rust | release-runtime-graph | MIT |
| `camino` | 1.2.6 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `cargo-platform` | 0.1.9 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `cargo_metadata` | 0.19.2 | rust | release-runtime-graph | MIT |
| `cfb` | 0.14.0 | rust | release-runtime-graph | MIT |
| `cfg-if` | 1.0.5 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `chrono` | 0.4.45 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `cookie` | 0.18.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `core_detect` | 1.0.0 | rust | release-runtime-graph | MIT/Apache-2.0 |
| `crossbeam-channel` | 0.5.17 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `crossbeam-utils` | 0.8.23 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `cssparser` | 0.37.0 | rust | release-runtime-graph | MPL-2.0 |
| `ctor` | 1.0.13 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `defmt` | 1.2.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `deranged` | 0.5.9 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `derive_more` | 2.1.1 | rust | release-runtime-graph | MIT |
| `dirs` | 7.0.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `dirs-sys` | 0.5.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `dom_query` | 0.28.0 | rust | release-runtime-graph | MIT |
| `dpi` | 0.1.2 | rust | release-runtime-graph | Apache-2.0 AND MIT |
| `dtoa` | 1.0.11 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `dtoa-short` | 0.3.5 | rust | release-runtime-graph | MPL-2.0 |
| `dunce` | 1.0.5 | rust | release-runtime-graph | CC0-1.0 OR MIT-0 OR Apache-2.0 |
| `dyn-clone` | 1.0.20 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `encoding_rs` | 0.8.44 | rust | release-runtime-graph | (Apache-2.0 OR MIT) AND BSD-3-Clause |
| `equivalent` | 1.0.3 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `erased-serde` | 0.4.11 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `fern` | 0.7.1 | rust | release-runtime-graph | MIT |
| `fnv` | 1.0.7 | rust | release-runtime-graph | Apache-2.0 / MIT |
| `foldhash` | 0.2.0 | rust | release-runtime-graph | Zlib |
| `form_urlencoded` | 1.2.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `getrandom` | 0.3.4 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `getrandom` | 0.4.3 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `glob` | 0.3.4 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `global-hotkey` | 0.8.0 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `hashbrown` | 0.12.3 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `hashbrown` | 0.17.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `heck` | 0.5.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `hex` | 0.4.3 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `html5ever` | 0.39.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `http` | 1.5.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `icu_collections` | 2.4.0 | rust | release-runtime-graph | Unicode-3.0 |
| `icu_locale_core` | 2.4.0 | rust | release-runtime-graph | Unicode-3.0 |
| `icu_normalizer` | 2.4.0 | rust | release-runtime-graph | Unicode-3.0 |
| `icu_normalizer_data` | 2.4.0 | rust | release-runtime-graph | Unicode-3.0 |
| `icu_properties` | 2.4.0 | rust | release-runtime-graph | Unicode-3.0 |
| `icu_properties_data` | 2.4.0 | rust | release-runtime-graph | Unicode-3.0 |
| `icu_provider` | 2.4.0 | rust | release-runtime-graph | Unicode-3.0 |
| `idna` | 1.1.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `idna_adapter` | 1.2.2 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `indexmap` | 1.9.3 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `indexmap` | 2.14.2 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `infer` | 0.22.0 | rust | release-runtime-graph | MIT |
| `itoa` | 1.0.18 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `jiff` | 0.2.39 | rust | release-runtime-graph | Unlicense OR MIT |
| `jiff-core` | 0.1.2 | rust | release-runtime-graph | Unlicense OR MIT |
| `jiff-tzdb` | 0.1.9 | rust | release-runtime-graph | Unlicense OR MIT |
| `jiff-tzdb-platform` | 0.1.3 | rust | release-runtime-graph | Unlicense OR MIT |
| `json-patch` | 4.2.0 | rust | release-runtime-graph | MIT/Apache-2.0 |
| `jsonptr` | 0.7.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `keyboard-types` | 0.7.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `keyboard-types` | 0.8.3 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `libc` | 0.2.191 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `litemap` | 0.8.3 | rust | release-runtime-graph | Unicode-3.0 |
| `lock_api` | 0.4.14 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `log` | 0.4.35 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `markup5ever` | 0.39.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `memchr` | 2.8.3 | rust | release-runtime-graph | Unlicense OR MIT |
| `mime` | 0.3.18 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `mio` | 1.2.4 | rust | release-runtime-graph | MIT |
| `muda` | 0.20.0 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `new_debug_unreachable` | 1.0.6 | rust | release-runtime-graph | MIT |
| `num-conv` | 0.2.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `num-traits` | 0.2.19 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `once_cell` | 1.21.4 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `open` | 5.4.5 | rust | release-runtime-graph | MIT |
| `option-ext` | 0.2.0 | rust | release-runtime-graph | MPL-2.0 |
| `os_pipe` | 1.2.3 | rust | release-runtime-graph | MIT |
| `parking_lot` | 0.12.5 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `parking_lot_core` | 0.9.12 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `percent-encoding` | 2.3.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `phf` | 0.13.1 | rust | release-runtime-graph | MIT |
| `phf_shared` | 0.13.1 | rust | release-runtime-graph | MIT |
| `pin-project-lite` | 0.2.17 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `plist` | 1.10.3 | rust | release-runtime-graph | MIT |
| `potential_utf` | 0.1.6 | rust | release-runtime-graph | Unicode-3.0 |
| `powerfmt` | 0.2.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `precomputed-hash` | 0.1.1 | rust | release-runtime-graph | MIT |
| `proc-macro2` | 1.0.107 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `quick-xml` | 0.42.0 | rust | release-runtime-graph | MIT |
| `quote` | 1.0.47 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `raw-window-handle` | 0.6.2 | rust | release-runtime-graph | MIT OR Apache-2.0 OR Zlib |
| `ref-cast` | 1.0.27 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `regex` | 1.13.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `regex-automata` | 0.4.18 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `regex-syntax` | 0.8.11 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `rustc-hash` | 2.1.3 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `same-file` | 1.0.6 | rust | release-runtime-graph | Unlicense/MIT |
| `schemars` | 0.8.22 | rust | release-runtime-graph | MIT |
| `schemars` | 0.9.0 | rust | release-runtime-graph | MIT |
| `schemars` | 1.2.3 | rust | release-runtime-graph | MIT |
| `scopeguard` | 1.2.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `selectors` | 0.38.0 | rust | release-runtime-graph | MPL-2.0 |
| `semver` | 1.0.28 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `serde` | 1.0.229 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `serde-untagged` | 0.1.9 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `serde_core` | 1.0.229 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `serde_json` | 1.0.154 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `serde_spanned` | 1.1.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `serde_with` | 3.24.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `serialize-to-javascript` | 0.1.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `servo_arc` | 0.4.3 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `shared_child` | 1.1.2 | rust | release-runtime-graph | MIT |
| `simdutf8` | 0.1.5 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `siphasher` | 1.0.4 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `smallvec` | 1.16.4 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `socket2` | 0.6.5 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `softbuffer` | 0.4.8 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `stable_deref_trait` | 1.2.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `string_cache` | 0.9.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `tao` | 0.37.2 | rust | release-runtime-graph | Apache-2.0 |
| `tauri` | 2.12.5 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `tauri-plugin-global-shortcut` | 2.4.1 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `tauri-plugin-log` | 2.10.1 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `tauri-plugin-shell` | 2.6.0 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `tauri-plugin-window-state` | 2.5.0 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `tauri-runtime` | 2.12.2 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `tauri-runtime-wry` | 2.12.3 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `tauri-utils` | 2.10.2 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `tendril` | 0.5.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `thiserror` | 2.0.21 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `time` | 0.3.55 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `time-core` | 0.1.9 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `tinystr` | 0.8.5 | rust | release-runtime-graph | Unicode-3.0 |
| `tinyvec` | 1.13.3 | rust | release-runtime-graph | Zlib OR Apache-2.0 OR MIT |
| `tokio` | 1.54.1 | rust | release-runtime-graph | MIT |
| `toml` | 1.2.0+spec-1.1.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `toml_datetime` | 1.1.2+spec-1.1.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `toml_parser` | 1.1.5+spec-1.1.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `toml_writer` | 1.2.0+spec-1.1.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `tracing` | 0.1.44 | rust | release-runtime-graph | MIT |
| `tracing-core` | 0.1.36 | rust | release-runtime-graph | MIT |
| `tray-icon` | 0.25.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `typeid` | 1.0.3 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `unicode-ident` | 1.0.27 | rust | release-runtime-graph | (MIT OR Apache-2.0) AND Unicode-3.0 |
| `unicode-segmentation` | 1.13.3 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `url` | 2.5.8 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `urlpattern` | 0.6.0 | rust | release-runtime-graph | MIT |
| `utf8_iter` | 1.1.0 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `utf_types` | 1.0.0 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `uuid` | 1.29.0 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `walkdir` | 2.5.0 | rust | release-runtime-graph | Unlicense/MIT |
| `web-time` | 1.1.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `web_atoms` | 0.2.6 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `webview2-com` | 0.39.1 | rust | release-runtime-graph | MIT |
| `webview2-com-sys` | 0.39.1 | rust | release-runtime-graph | MIT |
| `winapi-util` | 0.1.11 | rust | release-runtime-graph | Unlicense OR MIT |
| `window-vibrancy` | 0.8.1 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `windows` | 0.62.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-collections` | 0.3.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-core` | 0.62.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-future` | 0.3.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-link` | 0.2.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-numerics` | 0.3.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-result` | 0.4.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-strings` | 0.5.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-sys` | 0.59.0 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-sys` | 0.60.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-sys` | 0.61.2 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-targets` | 0.52.6 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-targets` | 0.53.5 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-threading` | 0.2.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows-version` | 0.1.7 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows_x86_64_msvc` | 0.52.6 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `windows_x86_64_msvc` | 0.53.1 | rust | release-runtime-graph | MIT OR Apache-2.0 |
| `winnow` | 1.0.5 | rust | release-runtime-graph | MIT |
| `writeable` | 0.6.4 | rust | release-runtime-graph | Unicode-3.0 |
| `wry` | 0.57.1 | rust | release-runtime-graph | Apache-2.0 OR MIT |
| `yoke` | 0.8.4 | rust | release-runtime-graph | Unicode-3.0 |
| `zerofrom` | 0.1.8 | rust | release-runtime-graph | Unicode-3.0 |
| `zerotrie` | 0.2.5 | rust | release-runtime-graph | Unicode-3.0 |
| `zerovec` | 0.11.9 | rust | release-runtime-graph | Unicode-3.0 |
| `zmij` | 1.0.23 | rust | release-runtime-graph | MIT |

## Retained non-release graph evidence

The durable inventory retains 383 additional components. See `sbom/dependency-license-inventory.csv` in the release directory or exact-commit CI evidence artifact for their versions, roles, licenses, and evidence classifications.

## Elite Dangerous and Frontier Developments

OmniCOVAS is an independent, unofficial project. It is not affiliated with, endorsed by, sponsored by, approved by, or connected to Frontier Developments plc. Elite Dangerous, Frontier Developments, COVAS, and related names, marks, and assets belong to their respective owners.

## Game knowledge sources

Galactic knowledge packs hold original OmniCOVAS records of Elite Dangerous game facts. The facts were researched from the references below, which are credited for transparency. Unless a pack states a content licence, no text, images, tables or code from these references are included.

### Galactic Atlas (omnicovas-galactic-atlas 2026-10-31-1)

- Elite Dangerous Wiki: Jameson Memorial: <https://elite-dangerous.fandom.com/wiki/Jameson_Memorial> (revision 174205; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: John Jameson: <https://elite-dangerous.fandom.com/wiki/John_Jameson> (revision 171617; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Shinrarta Dezhra: <https://elite-dangerous.fandom.com/wiki/Shinrarta_Dezhra> (revision 174166; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Founders World: <https://elite-dangerous.fandom.com/wiki/Founders_World> (revision 145239; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Jameson family: <https://elite-dangerous.fandom.com/wiki/Jameson_family> (revision 162099; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Peter Jameson: <https://elite-dangerous.fandom.com/wiki/Peter_Jameson> (revision 173194; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Intergalactic Naval Reserve Arm: <https://elite-dangerous.fandom.com/wiki/Intergalactic_Naval_Reserve_Arm> (revision 165462; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Mycoid: <https://elite-dangerous.fandom.com/wiki/Mycoid> (revision 162214; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: First Thargoid War: <https://elite-dangerous.fandom.com/wiki/First_Thargoid_War> (revision 170042; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: League of Reparation: <https://elite-dangerous.fandom.com/wiki/League_of_Reparation> (revision 165670; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Pilots Federation: <https://elite-dangerous.fandom.com/wiki/Pilots_Federation> (revision 174221; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Data point: <https://elite-dangerous.fandom.com/wiki/Data_point> (revision 141847; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Generation Ship: <https://elite-dangerous.fandom.com/wiki/Generation_Ship> (revision 173400; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Hutton Orbital: <https://elite-dangerous.fandom.com/wiki/Hutton_Orbital> (revision 169888; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- E:D Black Box: Jameson Crash Site farming guide: <https://edblackbox.com/guides/engineering/materials-and-farming/jameson-crash-site.html> (reviewed 2026-10-29; Licence not stated; facts restated, no text copied)
- EDSM public system, body and station records: <https://www.edsm.net/en/api-v1> (reviewed 2026-10-29; Licence not reviewed; only game identifiers recorded)
- EDSM public body records (radius): <https://www.edsm.net/en/api-system-v1> (reviewed 2026-10-31; Licence not reviewed; only game facts recorded)
- EDCD/FDevIDs material table (encoded materials): <https://github.com/EDCD/FDevIDs/blob/master/material.csv> (reviewed 2026-10-29; No dataset licence stated)
- GalNet articles cited by the wiki (INRA condemnation, League of Reparation): <https://www.elitedangerous.com/news/galnet> (reviewed 2026-10-29; Frontier content; not retrieved; not retrieved)
- r/EliteDangerous discovery thread for Jameson's Cobra (cited by the wiki): <https://www.reddit.com/r/EliteDangerous/comments/7ff8ln/cmdr_jameson_cobra_mk3_found/> (reviewed 2026-10-29; Licence not reviewed; not retrieved; not retrieved)
- Canonn Research codex (INRA bases): <https://canonn.science/codex/> (reviewed 2026-10-29; Licence not reviewed; not retrieved; not retrieved)

### Galactic Expeditions (omnicovas-galactic-expeditions 2026-11-02-1)

- EDSM public system records (curation-time positions): <https://www.edsm.net/en/api-v1> (reviewed 2026-10-30; Licence not reviewed; only game identifiers and coordinates recorded)

### Galactic Historian: the founding powers, Colonia, the great mysteries, the Missing and the Thargoid wars (omnicovas-galactic-historian 2026-11-02-1)

- Elite Dangerous Wiki: Sol: <https://elite-dangerous.fandom.com/wiki/Sol> (revision 169027; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Achenar: <https://elite-dangerous.fandom.com/wiki/Achenar> (revision 167726; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Alioth: <https://elite-dangerous.fandom.com/wiki/Alioth> (revision 168489; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Federation: <https://elite-dangerous.fandom.com/wiki/Federation> (revision 173492; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Empire: <https://elite-dangerous.fandom.com/wiki/Empire> (revision 173496; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Alliance: <https://elite-dangerous.fandom.com/wiki/Alliance> (revision 172287; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Marlin Duval: <https://elite-dangerous.fandom.com/wiki/Marlin_Duval> (revision 154838; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Henson Duval: <https://elite-dangerous.fandom.com/wiki/Henson_Duval> (revision 169317; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Mic Turner: <https://elite-dangerous.fandom.com/wiki/Mic_Turner> (revision 152557; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Meredith Argent: <https://elite-dangerous.fandom.com/wiki/Meredith_Argent> (revision 156636; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Battle of Achenar: <https://elite-dangerous.fandom.com/wiki/Battle_of_Achenar> (revision 167708; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Nine Martyrs: <https://elite-dangerous.fandom.com/wiki/Nine_Martyrs> (revision 162421; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Colonia: <https://elite-dangerous.fandom.com/wiki/Colonia> (revision 173926; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Jaques Station: <https://elite-dangerous.fandom.com/wiki/Jaques_Station> (revision 171786; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Jaques: <https://elite-dangerous.fandom.com/wiki/Jaques> (revision 171787; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Colonia Council: <https://elite-dangerous.fandom.com/wiki/Colonia_Council> (revision 169400; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: The Dark Wheel: <https://elite-dangerous.fandom.com/wiki/The_Dark_Wheel> (revision 171950; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Raxxla: <https://elite-dangerous.fandom.com/wiki/Raxxla> (revision 174267; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Formidine Rift: <https://elite-dangerous.fandom.com/wiki/Formidine_Rift> (revision 171354; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Project Dynasty: <https://elite-dangerous.fandom.com/wiki/Project_Dynasty> (revision 164559; reviewed 2026-10-31; CC BY-SA (Fandom community content))
- EDSM public system and station records (GKI-07): <https://www.edsm.net/en/api-v1> (reviewed 2026-10-31; Licence not reviewed; only game identifiers recorded)
- Elite Dangerous Wiki: Generation Ship: <https://elite-dangerous.fandom.com/wiki/Generation_Ship> (revision 173400; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Thargoid Titan: <https://elite-dangerous.fandom.com/wiki/Thargoid_Titan> (revision 173586; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Second Thargoid War: <https://elite-dangerous.fandom.com/wiki/Second_Thargoid_War> (revision 173536; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Crashed Thargoid Ship: <https://elite-dangerous.fandom.com/wiki/Crashed_Thargoid_Ship> (revision 154133; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Delphi: <https://elite-dangerous.fandom.com/wiki/Delphi> (revision 166344; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Obsidian Orbital: <https://elite-dangerous.fandom.com/wiki/Obsidian_Orbital> (revision 163922; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Aegis: <https://elite-dangerous.fandom.com/wiki/Aegis> (revision 161896; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Salvation: <https://elite-dangerous.fandom.com/wiki/Salvation> (revision 169858; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Li Qing Jao: <https://elite-dangerous.fandom.com/wiki/Li_Qing_Jao> (revision 151247; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Li Qin Jao: <https://elite-dangerous.fandom.com/wiki/Li_Qin_Jao> (revision 154404; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Dawes Hub: <https://elite-dangerous.fandom.com/wiki/Dawes_Hub> (revision 144280; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Donaldson: <https://elite-dangerous.fandom.com/wiki/Donaldson> (revision 144281; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Lave Station: <https://elite-dangerous.fandom.com/wiki/Lave_Station> (revision 142052; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Galactic Cooperative: <https://elite-dangerous.fandom.com/wiki/Galactic_Cooperative> (revision 162392; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Leonard Nimoy Station: <https://elite-dangerous.fandom.com/wiki/Leonard_Nimoy_Station> (revision 141766; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Memorial CMDR Garak: <https://elite-dangerous.fandom.com/wiki/Memorial_CMDR_Garak> (revision 171656; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Mars High: <https://elite-dangerous.fandom.com/wiki/Mars_High> (revision 151248; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- EDSM public system, station and body records (curation-time identifiers): <https://www.edsm.net/en/api-v1> (reviewed 2026-11-02; Licence not reviewed; only game identifiers, coordinates and body radii recorded)

### Guardian technology (omnicovas-guardian-technology 2026-11-02-1)

- Elite Dangerous Wiki: Guardian Frame Shift Drive Booster: <https://elite-dangerous.fandom.com/wiki/Guardian_Frame_Shift_Drive_Booster> (revision 169902; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Technology Broker: <https://elite-dangerous.fandom.com/wiki/Technology_Broker> (revision 173844; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Module Blueprint Fragment: <https://elite-dangerous.fandom.com/wiki/Guardian_Module_Blueprint_Fragment> (revision 166099; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Structure: <https://elite-dangerous.fandom.com/wiki/Guardian_Structure> (revision 169434; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Ancient Data Terminal: <https://elite-dangerous.fandom.com/wiki/Ancient_Data_Terminal> (revision 164463; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Power Cell: <https://elite-dangerous.fandom.com/wiki/Guardian_Power_Cell> (revision 159746; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Technology Component: <https://elite-dangerous.fandom.com/wiki/Guardian_Technology_Component> (revision 155176; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Focus Crystals: <https://elite-dangerous.fandom.com/wiki/Focus_Crystals> (revision 156775; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: HN Shock Mount: <https://elite-dangerous.fandom.com/wiki/HN_Shock_Mount> (revision 155432; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Relic: <https://elite-dangerous.fandom.com/wiki/Guardian_Relic> (revision 169567; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Frontier Player Journal documentation: TechnologyBroker event (community-hosted copy): <https://elite-journal.readthedocs.io/en/latest/Station%20Services.html> (reviewed 2026-10-29; Frontier documentation; event shape only)
- EDCD/FDevIDs material, commodity and outfitting tables: <https://github.com/EDCD/FDevIDs> (reviewed 2026-10-29; No dataset licence stated)
- Canonn Research: Guardian structure codex: <https://canonn.science/codex/guardian-structure/> (reviewed 2026-10-29; Licence not reviewed; not retrieved)
- Elite Dangerous Wiki: Guardian Gauss Cannon: <https://elite-dangerous.fandom.com/wiki/Guardian_Gauss_Cannon> (revision 169022; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Plasma Charger: <https://elite-dangerous.fandom.com/wiki/Guardian_Plasma_Charger> (revision 169023; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Shard Cannon: <https://elite-dangerous.fandom.com/wiki/Guardian_Shard_Cannon> (revision 169230; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Hybrid Power Plant: <https://elite-dangerous.fandom.com/wiki/Guardian_Hybrid_Power_Plant> (revision 169281; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Hybrid Power Distributor: <https://elite-dangerous.fandom.com/wiki/Guardian_Hybrid_Power_Distributor> (revision 169280; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Hull Reinforcement Package: <https://elite-dangerous.fandom.com/wiki/Guardian_Hull_Reinforcement_Package> (revision 165842; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Module Reinforcement Package: <https://elite-dangerous.fandom.com/wiki/Guardian_Module_Reinforcement_Package> (revision 170069; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Shield Reinforcement Package: <https://elite-dangerous.fandom.com/wiki/Guardian_Shield_Reinforcement_Package> (revision 170059; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: XG7 Trident: <https://elite-dangerous.fandom.com/wiki/XG7_Trident> (revision 171075; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: XG8 Javelin: <https://elite-dangerous.fandom.com/wiki/XG8_Javelin> (revision 171076; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: XG9 Lance: <https://elite-dangerous.fandom.com/wiki/XG9_Lance> (revision 171077; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Weapon Blueprint Fragment: <https://elite-dangerous.fandom.com/wiki/Guardian_Weapon_Blueprint_Fragment> (revision 135027; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Vessel Blueprint Fragment: <https://elite-dangerous.fandom.com/wiki/Guardian_Vessel_Blueprint_Fragment> (revision 155553; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Power Conduit: <https://elite-dangerous.fandom.com/wiki/Guardian_Power_Conduit> (revision 135023; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Sentinel Weapon Parts: <https://elite-dangerous.fandom.com/wiki/Guardian_Sentinel_Weapon_Parts> (revision 135024; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Wreckage Components: <https://elite-dangerous.fandom.com/wiki/Guardian_Wreckage_Components> (revision 135766; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Pattern Alpha Obelisk Data: <https://elite-dangerous.fandom.com/wiki/Pattern_Alpha_Obelisk_Data> (revision 135061; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Pattern Beta Obelisk Data: <https://elite-dangerous.fandom.com/wiki/Pattern_Beta_Obelisk_Data> (revision 135062; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Pattern Gamma Obelisk Data: <https://elite-dangerous.fandom.com/wiki/Pattern_Gamma_Obelisk_Data> (revision 135065; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Pattern Delta Obelisk Data: <https://elite-dangerous.fandom.com/wiki/Pattern_Delta_Obelisk_Data> (revision 135063; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Pattern Epsilon Obelisk Data: <https://elite-dangerous.fandom.com/wiki/Pattern_Epsilon_Obelisk_Data> (revision 136445; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Beacon: <https://elite-dangerous.fandom.com/wiki/Guardian_Beacon> (revision 165900; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Ancient Key: <https://elite-dangerous.fandom.com/wiki/Ancient_Key> (revision 156274; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Ancient Ruins: <https://elite-dangerous.fandom.com/wiki/Ancient_Ruins> (revision 156643; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Guardian Sentinel: <https://elite-dangerous.fandom.com/wiki/Guardian_Sentinel> (revision 165899; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Vessel Hangar: <https://elite-dangerous.fandom.com/wiki/Vessel_Hangar> (revision 172819; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Magnetic Emitter Coil: <https://elite-dangerous.fandom.com/wiki/Magnetic_Emitter_Coil> (revision 174138; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Reinforced Mounting Plate: <https://elite-dangerous.fandom.com/wiki/Reinforced_Mounting_Plate> (revision 155430; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Heatsink Interlink: <https://elite-dangerous.fandom.com/wiki/Heatsink_Interlink> (revision 174135; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Energy Grid Assembly: <https://elite-dangerous.fandom.com/wiki/Energy_Grid_Assembly> (revision 174137; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Micro-Weave Cooling Hoses: <https://elite-dangerous.fandom.com/wiki/Micro-Weave_Cooling_Hoses> (revision 155913; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Articulation Motors: <https://elite-dangerous.fandom.com/wiki/Articulation_Motors> (revision 155381; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Power Transfer Bus: <https://elite-dangerous.fandom.com/wiki/Power_Transfer_Bus> (revision 155454; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Micro Controllers: <https://elite-dangerous.fandom.com/wiki/Micro_Controllers> (revision 155712; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Hardware Diagnostic Sensor: <https://elite-dangerous.fandom.com/wiki/Hardware_Diagnostic_Sensor> (revision 155707; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Thermal Cooling Units: <https://elite-dangerous.fandom.com/wiki/Thermal_Cooling_Units> (revision 155461; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Power Converter: <https://elite-dangerous.fandom.com/wiki/Power_Converter> (revision 155369; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Manganese: <https://elite-dangerous.fandom.com/wiki/Manganese> (revision 154562; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Chromium: <https://elite-dangerous.fandom.com/wiki/Chromium> (revision 154557; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Carbon: <https://elite-dangerous.fandom.com/wiki/Carbon> (revision 154553; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Niobium: <https://elite-dangerous.fandom.com/wiki/Niobium> (revision 154554; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Arsenic: <https://elite-dangerous.fandom.com/wiki/Arsenic> (revision 166021; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Germanium: <https://elite-dangerous.fandom.com/wiki/Germanium> (revision 156554; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Phase Alloys: <https://elite-dangerous.fandom.com/wiki/Phase_Alloys> (revision 154714; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Heat Resistant Ceramics: <https://elite-dangerous.fandom.com/wiki/Heat_Resistant_Ceramics> (revision 154626; reviewed 2026-10-29; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Raw Materials: <https://elite-dangerous.fandom.com/wiki/Raw_Materials> (revision 166145; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Outcrop: <https://elite-dangerous.fandom.com/wiki/Outcrop> (revision 152087; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Materials: <https://elite-dangerous.fandom.com/wiki/Materials> (revision 171277; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Manufactured Materials: <https://elite-dangerous.fandom.com/wiki/Manufactured_Materials> (revision 168007; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Mission Board: <https://elite-dangerous.fandom.com/wiki/Mission_Board> (revision 168466; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Mining Laser: <https://elite-dangerous.fandom.com/wiki/Mining_Laser> (revision 168713; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Collector Limpet Controller: <https://elite-dangerous.fandom.com/wiki/Collector_Limpet_Controller> (revision 169969; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Planetary Vehicle Hangar: <https://elite-dangerous.fandom.com/wiki/Planetary_Vehicle_Hangar> (revision 172480; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Unidentified Signal Source: <https://elite-dangerous.fandom.com/wiki/Unidentified_Signal_Source> (revision 159813; reviewed 2026-11-02; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Settlement: <https://elite-dangerous.fandom.com/wiki/Settlement> (revision 173174; reviewed 2026-11-02; CC BY-SA (Fandom community content))

### Material Acquisition (omnicovas-material-acquisition 2026-10-30-2)

- Elite Dangerous Wiki: Materials: <https://elite-dangerous.fandom.com/wiki/Materials> (revision 171277; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Raw Materials: <https://elite-dangerous.fandom.com/wiki/Raw_Materials> (revision 166145; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Manufactured Materials: <https://elite-dangerous.fandom.com/wiki/Manufactured_Materials> (revision 168007; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Encoded Materials: <https://elite-dangerous.fandom.com/wiki/Encoded_Materials> (revision 168005; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: High Grade Emissions: <https://elite-dangerous.fandom.com/wiki/High_Grade_Emissions> (revision 168751; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Degraded Emissions: <https://elite-dangerous.fandom.com/wiki/Degraded_Emissions> (revision 166052; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Encoded Emissions: <https://elite-dangerous.fandom.com/wiki/Encoded_Emissions> (revision 144936; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Private Data Beacons: <https://elite-dangerous.fandom.com/wiki/Private_Data_Beacons> (revision 152863; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Satellite: <https://elite-dangerous.fandom.com/wiki/Satellite> (revision 145401; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Data point: <https://elite-dangerous.fandom.com/wiki/Data_point> (revision 141847; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Data Link Scanner: <https://elite-dangerous.fandom.com/wiki/Data_Link_Scanner> (revision 170168; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Hackable Comms Array: <https://elite-dangerous.fandom.com/wiki/Hackable_Comms_Array> (revision 155554; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Hackable Data Transmitter: <https://elite-dangerous.fandom.com/wiki/Hackable_Data_Transmitter> (revision 153069; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Frame Shift Wake Scanner: <https://elite-dangerous.fandom.com/wiki/Frame_Shift_Wake_Scanner> (revision 162904; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Crystalline Shard: <https://elite-dangerous.fandom.com/wiki/Crystalline_Shard> (revision 169408; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Crystalline Cluster: <https://elite-dangerous.fandom.com/wiki/Crystalline_Cluster> (revision 139628; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Needle Crystals: <https://elite-dangerous.fandom.com/wiki/Needle_Crystals> (revision 147937; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Crystalline Fragments: <https://elite-dangerous.fandom.com/wiki/Crystalline_Fragments> (revision 147933; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Outcrop: <https://elite-dangerous.fandom.com/wiki/Outcrop> (revision 152087; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Metallic Meteorite: <https://elite-dangerous.fandom.com/wiki/Metallic_Meteorite> (revision 163888; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Miner: <https://elite-dangerous.fandom.com/wiki/Miner> (revision 174119; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Cargo Scoop: <https://elite-dangerous.fandom.com/wiki/Cargo_Scoop> (revision 160142; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Detailed Surface Scanner: <https://elite-dangerous.fandom.com/wiki/Detailed_Surface_Scanner> (revision 165867; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Mission Board: <https://elite-dangerous.fandom.com/wiki/Mission_Board> (revision 168466; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Brain Tree: <https://elite-dangerous.fandom.com/wiki/Brain_Tree> (revision 172544; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Fungal Life: <https://elite-dangerous.fandom.com/wiki/Fungal_Life> (revision 172543; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Phloem Excretion: <https://elite-dangerous.fandom.com/wiki/Phloem_Excretion> (revision 147935; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Polyporous Growth: <https://elite-dangerous.fandom.com/wiki/Polyporous_Growth> (revision 151106; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Mussidaen Seed Pod: <https://elite-dangerous.fandom.com/wiki/Mussidaen_Seed_Pod> (revision 147936; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Cordycep Growth: <https://elite-dangerous.fandom.com/wiki/Cordycep_Growth> (revision 147934; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Cargo Rack (Wreckage): <https://elite-dangerous.fandom.com/wiki/Cargo_Rack_(Wreckage)> (revision 157379; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Anti-Xeno Initiative Wiki: Engineering Materials Guide: <https://wiki.antixenoinitiative.com/en/engineering-materials> (reviewed 2026-10-30; Licence not reviewed; facts restated, no text copied)
- Frontier Forums: Brain trees - new bug, or colonization is harming them? (May 2025): <https://forums.frontier.co.uk/threads/brain-trees-new-bug-or-colonization-is-harming-them.637367/> (reviewed 2026-10-30; Forum posts; facts restated, no text copied)
- Frontier Forums: Brain tree limpet farming - Limpets exploding (March 2025): <https://forums.frontier.co.uk/threads/brain-tree-limpet-farming-limpets-exploding.635893/> (reviewed 2026-10-30; Forum posts; facts restated, no text copied)
- Elite Dangerous Wiki: Carbon: <https://elite-dangerous.fandom.com/wiki/Carbon> (revision 154553; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Vanadium: <https://elite-dangerous.fandom.com/wiki/Vanadium> (revision 154539; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Niobium: <https://elite-dangerous.fandom.com/wiki/Niobium> (revision 154554; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Yttrium: <https://elite-dangerous.fandom.com/wiki/Yttrium> (revision 161618; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Phosphorus: <https://elite-dangerous.fandom.com/wiki/Phosphorus> (revision 154556; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Chromium: <https://elite-dangerous.fandom.com/wiki/Chromium> (revision 154557; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Molybdenum: <https://elite-dangerous.fandom.com/wiki/Molybdenum> (revision 154558; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Technetium: <https://elite-dangerous.fandom.com/wiki/Technetium> (revision 154559; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Sulphur: <https://elite-dangerous.fandom.com/wiki/Sulphur> (revision 154561; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Manganese: <https://elite-dangerous.fandom.com/wiki/Manganese> (revision 154562; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Cadmium: <https://elite-dangerous.fandom.com/wiki/Cadmium> (revision 168401; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Ruthenium: <https://elite-dangerous.fandom.com/wiki/Ruthenium> (revision 154564; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Iron: <https://elite-dangerous.fandom.com/wiki/Iron> (revision 154538; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Zinc: <https://elite-dangerous.fandom.com/wiki/Zinc> (revision 154567; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Tin: <https://elite-dangerous.fandom.com/wiki/Tin> (revision 154566; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Selenium: <https://elite-dangerous.fandom.com/wiki/Selenium> (revision 154565; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Nickel: <https://elite-dangerous.fandom.com/wiki/Nickel> (revision 154577; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Germanium: <https://elite-dangerous.fandom.com/wiki/Germanium> (revision 156554; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Tungsten: <https://elite-dangerous.fandom.com/wiki/Tungsten> (revision 154540; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Tellurium: <https://elite-dangerous.fandom.com/wiki/Tellurium> (revision 156868; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Rhenium: <https://elite-dangerous.fandom.com/wiki/Rhenium> (revision 154537; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Arsenic: <https://elite-dangerous.fandom.com/wiki/Arsenic> (revision 166021; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Mercury: <https://elite-dangerous.fandom.com/wiki/Mercury> (revision 169251; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Polonium: <https://elite-dangerous.fandom.com/wiki/Polonium> (revision 154571; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Lead: <https://elite-dangerous.fandom.com/wiki/Lead> (revision 154576; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Zirconium: <https://elite-dangerous.fandom.com/wiki/Zirconium> (revision 154575; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Boron: <https://elite-dangerous.fandom.com/wiki/Boron> (revision 168343; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Antimony: <https://elite-dangerous.fandom.com/wiki/Antimony> (revision 154573; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Chemical Storage Units: <https://elite-dangerous.fandom.com/wiki/Chemical_Storage_Units> (revision 154622; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Chemical Processors: <https://elite-dangerous.fandom.com/wiki/Chemical_Processors> (revision 172153; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Chemical Distillery: <https://elite-dangerous.fandom.com/wiki/Chemical_Distillery> (revision 154623; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Chemical Manipulators: <https://elite-dangerous.fandom.com/wiki/Chemical_Manipulators> (revision 154506; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Pharmaceutical Isolators: <https://elite-dangerous.fandom.com/wiki/Pharmaceutical_Isolators> (revision 165728; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Tempered Alloys: <https://elite-dangerous.fandom.com/wiki/Tempered_Alloys> (revision 154625; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Heat Resistant Ceramics: <https://elite-dangerous.fandom.com/wiki/Heat_Resistant_Ceramics> (revision 154626; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Precipitated Alloys: <https://elite-dangerous.fandom.com/wiki/Precipitated_Alloys> (revision 154627; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Thermic Alloys: <https://elite-dangerous.fandom.com/wiki/Thermic_Alloys> (revision 154628; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Military Grade Alloys: <https://elite-dangerous.fandom.com/wiki/Military_Grade_Alloys> (revision 162428; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Heat Conduction Wiring: <https://elite-dangerous.fandom.com/wiki/Heat_Conduction_Wiring> (revision 154686; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Heat Dispersion Plate: <https://elite-dangerous.fandom.com/wiki/Heat_Dispersion_Plate> (revision 154687; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Heat Exchangers: <https://elite-dangerous.fandom.com/wiki/Heat_Exchangers> (revision 154688; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Heat Vanes: <https://elite-dangerous.fandom.com/wiki/Heat_Vanes> (revision 156555; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Proto Heat Radiators: <https://elite-dangerous.fandom.com/wiki/Proto_Heat_Radiators> (revision 156556; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Basic Conductors: <https://elite-dangerous.fandom.com/wiki/Basic_Conductors> (revision 154734; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Conductive Components: <https://elite-dangerous.fandom.com/wiki/Conductive_Components> (revision 154735; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Conductive Ceramics: <https://elite-dangerous.fandom.com/wiki/Conductive_Ceramics> (revision 154736; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Conductive Polymers: <https://elite-dangerous.fandom.com/wiki/Conductive_Polymers> (revision 154737; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Biotech Conductors: <https://elite-dangerous.fandom.com/wiki/Biotech_Conductors> (revision 161881; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Mechanical Scrap: <https://elite-dangerous.fandom.com/wiki/Mechanical_Scrap> (revision 154738; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Mechanical Equipment: <https://elite-dangerous.fandom.com/wiki/Mechanical_Equipment> (revision 154739; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Mechanical Components: <https://elite-dangerous.fandom.com/wiki/Mechanical_Components> (revision 154740; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Configurable Components: <https://elite-dangerous.fandom.com/wiki/Configurable_Components> (revision 154741; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Improvised Components: <https://elite-dangerous.fandom.com/wiki/Improvised_Components> (revision 156561; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Grid Resistors: <https://elite-dangerous.fandom.com/wiki/Grid_Resistors> (revision 154730; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Hybrid Capacitors: <https://elite-dangerous.fandom.com/wiki/Hybrid_Capacitors> (revision 154731; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Electrochemical Arrays: <https://elite-dangerous.fandom.com/wiki/Electrochemical_Arrays> (revision 154732; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Polymer Capacitors: <https://elite-dangerous.fandom.com/wiki/Polymer_Capacitors> (revision 154733; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Military Supercapacitors: <https://elite-dangerous.fandom.com/wiki/Military_Supercapacitors> (revision 155954; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Worn Shield Emitters: <https://elite-dangerous.fandom.com/wiki/Worn_Shield_Emitters> (revision 154729; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Shield Emitters: <https://elite-dangerous.fandom.com/wiki/Shield_Emitters> (revision 154728; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Shielding Sensors: <https://elite-dangerous.fandom.com/wiki/Shielding_Sensors> (revision 154727; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Compound Shielding: <https://elite-dangerous.fandom.com/wiki/Compound_Shielding> (revision 154726; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Imperial Shielding: <https://elite-dangerous.fandom.com/wiki/Imperial_Shielding> (revision 156495; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Compact Composites: <https://elite-dangerous.fandom.com/wiki/Compact_Composites> (revision 154717; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Filament Composites: <https://elite-dangerous.fandom.com/wiki/Filament_Composites> (revision 154722; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: High Density Composites: <https://elite-dangerous.fandom.com/wiki/High_Density_Composites> (revision 154723; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Proprietary Composites: <https://elite-dangerous.fandom.com/wiki/Proprietary_Composites> (revision 154724; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Core Dynamics Composites: <https://elite-dangerous.fandom.com/wiki/Core_Dynamics_Composites> (revision 154725; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Crystal Shards: <https://elite-dangerous.fandom.com/wiki/Crystal_Shards> (revision 154709; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Flawed Focus Crystals: <https://elite-dangerous.fandom.com/wiki/Flawed_Focus_Crystals> (revision 154710; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Focus Crystals: <https://elite-dangerous.fandom.com/wiki/Focus_Crystals> (revision 156775; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Refined Focus Crystals: <https://elite-dangerous.fandom.com/wiki/Refined_Focus_Crystals> (revision 154711; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Exquisite Focus Crystals: <https://elite-dangerous.fandom.com/wiki/Exquisite_Focus_Crystals> (revision 154712; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Salvaged Alloys: <https://elite-dangerous.fandom.com/wiki/Salvaged_Alloys> (revision 154708; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Galvanising Alloys: <https://elite-dangerous.fandom.com/wiki/Galvanising_Alloys> (revision 154665; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Phase Alloys: <https://elite-dangerous.fandom.com/wiki/Phase_Alloys> (revision 154714; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Proto Light Alloys: <https://elite-dangerous.fandom.com/wiki/Proto_Light_Alloys> (revision 154715; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Proto Radiolic Alloys: <https://elite-dangerous.fandom.com/wiki/Proto_Radiolic_Alloys> (revision 154716; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Exceptional Scrambled Emission Data: <https://elite-dangerous.fandom.com/wiki/Exceptional_Scrambled_Emission_Data> (revision 139830; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Irregular Emission Data: <https://elite-dangerous.fandom.com/wiki/Irregular_Emission_Data> (revision 141842; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Unexpected Emission Data: <https://elite-dangerous.fandom.com/wiki/Unexpected_Emission_Data> (revision 154592; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Decoded Emission Data: <https://elite-dangerous.fandom.com/wiki/Decoded_Emission_Data> (revision 140231; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Abnormal Compact Emissions Data: <https://elite-dangerous.fandom.com/wiki/Abnormal_Compact_Emissions_Data> (revision 161691; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Atypical Disrupted Wake Echoes: <https://elite-dangerous.fandom.com/wiki/Atypical_Disrupted_Wake_Echoes> (revision 154514; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Anomalous FSD Telemetry: <https://elite-dangerous.fandom.com/wiki/Anomalous_FSD_Telemetry> (revision 136930; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Strange Wake Solutions: <https://elite-dangerous.fandom.com/wiki/Strange_Wake_Solutions> (revision 142686; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Eccentric Hyperspace Trajectories: <https://elite-dangerous.fandom.com/wiki/Eccentric_Hyperspace_Trajectories> (revision 154593; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Datamined Wake Exceptions: <https://elite-dangerous.fandom.com/wiki/Datamined_Wake_Exceptions> (revision 164112; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Distorted Shield Cycle Recordings: <https://elite-dangerous.fandom.com/wiki/Distorted_Shield_Cycle_Recordings> (revision 154594; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Inconsistent Shield Soak Analysis: <https://elite-dangerous.fandom.com/wiki/Inconsistent_Shield_Soak_Analysis> (revision 154597; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Untypical Shield Scans: <https://elite-dangerous.fandom.com/wiki/Untypical_Shield_Scans> (revision 153064; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Aberrant Shield Pattern Analysis: <https://elite-dangerous.fandom.com/wiki/Aberrant_Shield_Pattern_Analysis> (revision 134978; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Peculiar Shield Frequency Data: <https://elite-dangerous.fandom.com/wiki/Peculiar_Shield_Frequency_Data> (revision 135066; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Unusual Encrypted Files: <https://elite-dangerous.fandom.com/wiki/Unusual_Encrypted_Files> (revision 154598; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Tagged Encryption Codes: <https://elite-dangerous.fandom.com/wiki/Tagged_Encryption_Codes> (revision 153056; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Open Symmetric Keys: <https://elite-dangerous.fandom.com/wiki/Open_Symmetric_Keys> (revision 135060; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Atypical Encryption Archives: <https://elite-dangerous.fandom.com/wiki/Atypical_Encryption_Archives> (revision 134985; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Adaptive Encryptors Capture: <https://elite-dangerous.fandom.com/wiki/Adaptive_Encryptors_Capture> (revision 134979; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Anomalous Bulk Scan Data: <https://elite-dangerous.fandom.com/wiki/Anomalous_Bulk_Scan_Data> (revision 153065; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Unidentified Scan Archives: <https://elite-dangerous.fandom.com/wiki/Unidentified_Scan_Archives> (revision 154602; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Classified Scan Databanks: <https://elite-dangerous.fandom.com/wiki/Classified_Scan_Databanks> (revision 154603; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Divergent Scan Data: <https://elite-dangerous.fandom.com/wiki/Divergent_Scan_Data> (revision 153067; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Classified Scan Fragment: <https://elite-dangerous.fandom.com/wiki/Classified_Scan_Fragment> (revision 153074; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Specialised Legacy Firmware: <https://elite-dangerous.fandom.com/wiki/Specialised_Legacy_Firmware> (revision 135090; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Modified Consumer Firmware: <https://elite-dangerous.fandom.com/wiki/Modified_Consumer_Firmware> (revision 154605; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Cracked Industrial Firmware: <https://elite-dangerous.fandom.com/wiki/Cracked_Industrial_Firmware> (revision 135006; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Security Firmware Patch: <https://elite-dangerous.fandom.com/wiki/Security_Firmware_Patch> (revision 153059; reviewed 2026-10-30; CC BY-SA (Fandom community content))
- Elite Dangerous Wiki: Modified Embedded Firmware: <https://elite-dangerous.fandom.com/wiki/Modified_Embedded_Firmware> (revision 154604; reviewed 2026-10-30; CC BY-SA (Fandom community content))

## Regeneration

```
.venv/Scripts/python.exe scripts/release/generate_sbom_inventory.py
.venv/Scripts/python.exe scripts/release/generate_third_party_notices.py
```

Regenerate after dependency or packaging-analysis changes. Publication remains held until the manual legal and release gates are accepted.
