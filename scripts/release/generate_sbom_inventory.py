"""Generate target-aware SBOM and dependency/license evidence.

Phase 10 reconciliation correction pass.

Evidence boundaries are intentionally explicit:

* Python release inclusion is derived from the PyInstaller ``Analysis-00.toc``
  produced for the packaged sidecar. Declared dependency closure is retained as
  secondary evidence, but an installed development tool is never called
  packaged merely because it exists in the build environment.
* Rust roles are derived from Cargo's resolved dependency graph filtered for
  ``x86_64-pc-windows-msvc``. Normal release dependencies, proc-macro/build
  dependencies, development dependencies, and target-excluded packages are
  separate classifications. This is graph evidence, not binary introspection.
* npm's complete package-lock graph (including development dependencies) is
  audited. The application ships plain ES modules and declares no npm runtime
  dependencies, so npm components are build/test tooling rather than release
  components.

License values come only from local package metadata. Unknown values fail the
command unless an exact entry with a rationale exists in
``scripts/release/sbom_license_allowlist.json``. An allowlist disposition is
not a license determination or a legal-compliance claim.

Outputs are written under ``artifacts/sbom/phase10-reconciliation/``. Release
packaging copies the durable set into ``dist/release/sbom/``.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import subprocess
import sys
import tomllib
from collections import Counter, defaultdict, deque
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Iterable

from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "artifacts" / "sbom" / "phase10-reconciliation"
ALLOWLIST_PATH = ROOT / "scripts" / "release" / "sbom_license_allowlist.json"
TARGET_TRIPLE = "x86_64-pc-windows-msvc"
UNKNOWN = "UNKNOWN"

# Release inclusion labels. They deliberately encode the evidence method.
DIST_PYTHON_PACKAGED_RUNTIME = "packaged-runtime"
DIST_PYTHON_PACKAGED_DEV = "packaged-development-tool"
DIST_PYTHON_PACKAGED_IMPLICIT = "packaged-implicit-import"
DIST_RUST_RUNTIME = "release-runtime-graph"
DIST_RUNTIME_NOT_OBSERVED = "declared-runtime-not-observed-in-sidecar"
DIST_BUILD = "build-only"
DIST_DEV = "development-only"
DIST_TARGET_EXCLUDED = "target-excluded"
RELEASE_DISTRIBUTIONS = {
    DIST_PYTHON_PACKAGED_RUNTIME,
    DIST_PYTHON_PACKAGED_DEV,
    DIST_PYTHON_PACKAGED_IMPLICIT,
    DIST_RUST_RUNTIME,
}


def _normalise(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def _run(command: list[str], *, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no diagnostic")[:1200]
        raise RuntimeError(f"{' '.join(command)} failed: {detail}")
    return result.stdout


def _license_from_metadata(dist: importlib_metadata.Distribution) -> str:
    """Return license metadata without guessing a missing value."""
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression and expression.strip():
        return expression.strip()

    classifiers = [
        value
        for key, value in meta.items()
        if key == "Classifier" and value.startswith("License ::")
    ]
    if classifiers:
        cleaned = [value.split("::")[-1].strip() for value in classifiers]
        cleaned = [value for value in cleaned if value and value != "OSI Approved"]
        if cleaned:
            return " OR ".join(sorted(set(cleaned)))

    legacy = meta.get("License")
    if legacy and legacy.strip():
        text = legacy.strip()
        if len(text) > 120 or "\n" in text:
            first = text.splitlines()[0].strip()
            return first[:120] if first else UNKNOWN
        return text
    return UNKNOWN


# ---------------------------------------------------------------------------
# Python: declared closure plus PyInstaller packaged-module analysis
# ---------------------------------------------------------------------------


def _target_marker_environment() -> dict[str, str]:
    environment = default_environment()
    environment.update(
        {
            "implementation_name": "cpython",
            "os_name": "nt",
            "platform_machine": "AMD64",
            "platform_system": "Windows",
            "python_full_version": "3.11.9",
            "python_version": "3.11",
            "sys_platform": "win32",
        }
    )
    return environment


def _marker_applies(requirement: Requirement, parent_extras: set[str]) -> bool:
    if requirement.marker is None:
        return True
    environment = _target_marker_environment()
    extras = parent_extras or {""}
    return any(
        requirement.marker.evaluate({**environment, "extra": extra}) for extra in extras
    )


def _project_requirements(group: str) -> list[Requirement]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if group == "runtime":
        values = data.get("project", {}).get("dependencies", [])
    elif group == "dev":
        values = data.get("dependency-groups", {}).get("dev", [])
    else:  # pragma: no cover - internal programming error
        raise ValueError(group)
    return [Requirement(value) for value in values]


def _dependency_closure(requirements: Iterable[Requirement]) -> set[str]:
    """Resolve installed metadata with PEP 508 markers/extras for Windows."""
    by_name = {
        _normalise(dist.metadata["Name"]): dist
        for dist in importlib_metadata.distributions()
        if dist.metadata.get("Name")
    }
    closure: set[str] = set()
    seen_states: set[tuple[str, tuple[str, ...]]] = set()
    queue: deque[tuple[str, set[str]]] = deque()

    for requirement in requirements:
        if _marker_applies(requirement, {""}):
            queue.append((_normalise(requirement.name), set(requirement.extras)))

    while queue:
        name, active_extras = queue.popleft()
        state = (name, tuple(sorted(active_extras)))
        if state in seen_states:
            continue
        seen_states.add(state)
        dist = by_name.get(name)
        if dist is None:
            continue
        closure.add(name)
        for value in dist.requires or []:
            requirement = Requirement(value)
            if _marker_applies(requirement, active_extras):
                queue.append((_normalise(requirement.name), set(requirement.extras)))
    return closure


def _find_pyinstaller_analysis() -> Path:
    candidates = sorted((ROOT / "build" / "tauri-sidecar").rglob("Analysis-00.toc"))
    if not candidates:
        raise RuntimeError(
            "PyInstaller Analysis-00.toc is missing. Run "
            "scripts/package/build_tauri_sidecar.ps1 before SBOM generation."
        )
    return candidates[-1]


def _analysis_module_entries(path: Path) -> list[tuple[set[str], Path]]:
    """Read import keys and source paths recorded by PyInstaller Analysis."""
    value = ast.literal_eval(path.read_text(encoding="utf-8"))
    if not isinstance(value, tuple) or len(value) < 16:
        raise RuntimeError(f"Unrecognised PyInstaller analysis format: {path}")

    entries: list[tuple[set[str], Path]] = []
    # Index 14 is pure modules; index 15 is binaries/extensions in PyInstaller 6.
    for entry in list(value[14]) + list(value[15]):
        if not isinstance(entry, tuple) or len(entry) < 2:
            continue
        logical_name = str(entry[0]).replace("\\", ".").replace("/", ".")
        source = Path(str(entry[1]))
        if "site-packages" not in {part.lower() for part in source.parts}:
            continue
        keys = {_normalise(logical_name.split(".", 1)[0])}
        lower_parts = [part.lower() for part in source.parts]
        index = lower_parts.index("site-packages")
        if index + 1 < len(source.parts):
            first = source.parts[index + 1]
            first = first.split(".", 1)[0].removesuffix(".libs")
            if first and not first.endswith("-info"):
                keys.add(_normalise(first))
        entries.append((keys, source.resolve()))
    return entries


def _packaged_distribution_names(analysis_path: Path) -> tuple[set[str], list[str]]:
    package_map = importlib_metadata.packages_distributions()
    normalised_map = {
        _normalise(module): {_normalise(name) for name in names}
        for module, names in package_map.items()
    }
    # Some legacy or namespace packages (notably pywin32's ``win32`` modules)
    # do not publish a complete top_level.txt, so packages_distributions() is
    # insufficient. Augment it from installed RECORD/file ownership. The
    # analysis already contributes both logical module names and the first
    # site-packages path component, allowing this map to catch hidden imports
    # and extension modules without guessing by dependency name.
    source_owners: dict[str, set[str]] = defaultdict(set)
    for dist in importlib_metadata.distributions():
        dist_name = dist.metadata.get("Name")
        if not dist_name:
            continue
        owner = _normalise(dist_name)
        for file in dist.files or []:
            if not file.parts:
                continue
            first = file.parts[0]
            if first in {"..", "."} or first.endswith((".dist-info", ".egg-info")):
                continue
            top_level = first.split(".", 1)[0].removesuffix(".libs")
            if top_level:
                normalised_map.setdefault(_normalise(top_level), set()).add(owner)
            try:
                located = Path(dist.locate_file(file)).resolve()
            except (OSError, RuntimeError):
                continue
            source_owners[str(located).casefold()].add(owner)

    entries = _analysis_module_entries(analysis_path)
    packaged: set[str] = set()
    unmapped: set[str] = set()
    for keys, source in entries:
        matches = set().union(
            *(normalised_map.get(key, set()) for key in keys),
            source_owners.get(str(source).casefold(), set()),
        )
        if matches:
            packaged.update(matches)
        else:
            unmapped.update(keys)
    return packaged, sorted(unmapped)


def collect_python() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    runtime_requirements = _project_requirements("runtime")
    dev_requirements = _project_requirements("dev")
    runtime_direct = {_normalise(req.name) for req in runtime_requirements}
    dev_direct = {_normalise(req.name) for req in dev_requirements}
    runtime_closure = _dependency_closure(runtime_requirements)
    dev_closure = _dependency_closure(dev_requirements)
    pyinstaller_closure = _dependency_closure(
        [req for req in dev_requirements if _normalise(req.name) == "pyinstaller"]
    )
    analysis_path = _find_pyinstaller_analysis()
    packaged, unmapped = _packaged_distribution_names(analysis_path)
    relevant_distributions = (
        runtime_closure | dev_closure | pyinstaller_closure | packaged
    )

    rows: list[dict[str, Any]] = []
    installed_names: set[str] = set()
    for dist in importlib_metadata.distributions():
        name = dist.metadata.get("Name")
        if not name:
            continue
        key = _normalise(name)
        if key == "omnicovas":
            continue
        installed_names.add(key)
        if key not in relevant_distributions:
            # Do not let unrelated packages that happen to be installed in the
            # build environment make the candidate evidence host-dependent.
            continue

        if key in packaged:
            if key in runtime_closure:
                distribution = DIST_PYTHON_PACKAGED_RUNTIME
            elif key in dev_closure:
                distribution = DIST_PYTHON_PACKAGED_DEV
            else:
                distribution = DIST_PYTHON_PACKAGED_IMPLICIT
            evidence = "PyInstaller Analysis-00.toc"
        elif key in runtime_closure:
            distribution = DIST_RUNTIME_NOT_OBSERVED
            evidence = "Windows marker-aware declared runtime closure only"
        elif key in pyinstaller_closure:
            distribution = DIST_BUILD
            evidence = "PyInstaller build-tool closure"
        else:
            distribution = DIST_DEV
            evidence = "Windows marker-aware declared development closure"

        rows.append(
            {
                "ecosystem": "python",
                "name": name,
                "version": dist.version or UNKNOWN,
                "license": _license_from_metadata(dist),
                "distribution": distribution,
                "direct": key in runtime_direct or key in dev_direct,
                "evidence": evidence,
                "roles": ";".join(
                    role
                    for role, present in (
                        ("packaged", key in packaged),
                        ("runtime-declared", key in runtime_closure),
                        ("build-tool", key in pyinstaller_closure),
                        ("development", key in dev_closure),
                    )
                    if present
                ),
            }
        )

    packaged_without_metadata = sorted(packaged - installed_names)
    if packaged_without_metadata:
        raise RuntimeError(
            "PyInstaller analysis mapped distributions absent from local metadata: "
            + ", ".join(packaged_without_metadata)
        )

    method = {
        "analysis_file": str(analysis_path.relative_to(ROOT)).replace("\\", "/"),
        "analysis_boundary": (
            "PyInstaller build analysis plus installed dist-info; not binary "
            "introspection"
        ),
        "declared_runtime_closure": len(runtime_closure),
        "declared_development_closure": len(dev_closure),
        "inventory_boundary": (
            "declared runtime/development closures plus PyInstaller analysis; "
            "unrelated installed distributions excluded"
        ),
        "packaged_distributions": len(packaged),
        "packaged_runtime_distributions": sum(
            1 for row in rows if row["distribution"] == DIST_PYTHON_PACKAGED_RUNTIME
        ),
        "packaged_development_tools": sum(
            1 for row in rows if row["distribution"] == DIST_PYTHON_PACKAGED_DEV
        ),
        "packaged_implicit_imports": sum(
            1 for row in rows if row["distribution"] == DIST_PYTHON_PACKAGED_IMPLICIT
        ),
        "unmapped_third_party_module_candidates": unmapped,
    }
    return sorted(rows, key=lambda row: _normalise(row["name"])), method


# ---------------------------------------------------------------------------
# Rust: target-filtered resolved graph with dependency-kind propagation
# ---------------------------------------------------------------------------


def _is_proc_macro(pkg: dict[str, Any]) -> bool:
    return any(
        "proc-macro" in target.get("kind", []) for target in pkg.get("targets", [])
    )


def _classify_rust_graph(data: dict[str, Any]) -> tuple[dict[str, set[str]], set[str]]:
    packages = {pkg["id"]: pkg for pkg in data.get("packages", [])}
    resolve = data.get("resolve") or {}
    nodes = {node["id"]: node for node in resolve.get("nodes", [])}
    workspace = set(data.get("workspace_members", []))
    roles: dict[str, set[str]] = defaultdict(set)
    visited: set[tuple[str, str]] = set()
    queue: deque[tuple[str, str]] = deque((member, "runtime") for member in workspace)

    while queue:
        package_id, role = queue.popleft()
        state = (package_id, role)
        if state in visited:
            continue
        visited.add(state)
        node = nodes.get(package_id)
        if node is None:
            continue
        for dependency in node.get("deps", []):
            dep_id = dependency["pkg"]
            dep_pkg = packages.get(dep_id, {})
            for dep_kind in dependency.get("dep_kinds", []):
                kind = dep_kind.get("kind") or "normal"
                if kind == "dev" and package_id not in workspace and role != "dev":
                    # Cargo does not build transitive dependencies' own dev deps.
                    continue
                if role == "dev" or kind == "dev":
                    next_role = "dev"
                elif role == "build" or kind == "build":
                    next_role = "build"
                elif _is_proc_macro(dep_pkg):
                    # Proc macros execute during compilation; their closure is
                    # build tooling even when Cargo models the edge as normal.
                    next_role = "build"
                else:
                    next_role = "runtime"
                roles[dep_id].add(next_role)
                queue.append((dep_id, next_role))
    return roles, workspace


def collect_rust() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    command = [
        "cargo",
        "metadata",
        "--format-version",
        "1",
        "--manifest-path",
        str(ROOT / "src-tauri" / "Cargo.toml"),
        "--locked",
        "--offline",
    ]
    # The filtered resolve graph determines what can participate in this
    # target build. The unfiltered package list is retained as conservative
    # build-graph evidence so other-platform packages remain visible without
    # being mislabelled as distributed in the Windows application.
    unfiltered = json.loads(_run(command))
    filtered = json.loads(_run([*command, "--filter-platform", TARGET_TRIPLE]))
    roles, workspace = _classify_rust_graph(filtered)
    filtered_ids = {pkg["id"] for pkg in filtered.get("packages", [])}

    direct_ids: set[str] = set()
    filtered_nodes = {
        node["id"]: node for node in (filtered.get("resolve") or {}).get("nodes", [])
    }
    for member in workspace:
        direct_ids.update(
            dependency["pkg"]
            for dependency in filtered_nodes.get(member, {}).get("deps", [])
        )

    rows: list[dict[str, Any]] = []
    for pkg in unfiltered.get("packages", []):
        package_id = pkg["id"]
        if package_id in workspace:
            continue
        package_roles = roles.get(package_id, set())
        if package_id not in filtered_ids:
            distribution = DIST_TARGET_EXCLUDED
        elif "runtime" in package_roles:
            distribution = DIST_RUST_RUNTIME
        elif "build" in package_roles:
            distribution = DIST_BUILD
        elif "dev" in package_roles:
            distribution = DIST_DEV
        else:
            distribution = DIST_TARGET_EXCLUDED

        license_value = pkg.get("license")
        if not license_value:
            license_value = (
                f"see {pkg['license_file']}" if pkg.get("license_file") else UNKNOWN
            )
        rows.append(
            {
                "ecosystem": "rust",
                "name": pkg.get("name", UNKNOWN),
                "version": pkg.get("version", UNKNOWN),
                "license": license_value,
                "distribution": distribution,
                "direct": package_id in direct_ids,
                "evidence": (
                    f"cargo resolve graph filtered for {TARGET_TRIPLE}; "
                    "unfiltered package list retained for excluded-target evidence"
                ),
                "roles": (
                    ";".join(sorted(package_roles)) or "excluded-from-target-resolve"
                ),
            }
        )

    method = {
        "target": TARGET_TRIPLE,
        "analysis_boundary": (
            "Cargo resolved dependency graph and dependency kinds; not final-binary "
            "composition or reachable-code analysis"
        ),
        "workspace_members": sorted(workspace),
        "unfiltered_packages_retained": len(unfiltered.get("packages", [])),
        "target_filtered_packages": len(filtered_ids),
    }
    return sorted(rows, key=lambda row: (row["name"], row["version"])), method


# ---------------------------------------------------------------------------
# npm: complete locked build/test graph, including development dependencies
# ---------------------------------------------------------------------------


def _licenses_from_cyclonedx(component: dict[str, Any]) -> str:
    values: list[str] = []
    for entry in component.get("licenses", []) or []:
        if entry.get("expression"):
            values.append(entry["expression"])
        elif isinstance(entry.get("license"), dict):
            license_value = entry["license"]
            values.append(
                license_value.get("id") or license_value.get("name") or UNKNOWN
            )
    return " OR ".join(sorted(set(values))) if values else UNKNOWN


def collect_npm() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = json.loads(
        _run(
            [
                "npm.cmd" if sys.platform == "win32" else "npm",
                "sbom",
                "--package-lock-only",
                "--sbom-format=cyclonedx",
            ]
        )
    )
    rows: list[dict[str, Any]] = []
    for component in data.get("components", []):
        name = component.get("name", UNKNOWN)
        if _normalise(name) == "omnicovas":
            continue
        rows.append(
            {
                "ecosystem": "npm",
                "name": name,
                "version": component.get("version", UNKNOWN),
                "license": _licenses_from_cyclonedx(component),
                "distribution": DIST_DEV,
                "direct": False,
                "evidence": "npm sbom --package-lock-only (development graph included)",
                "roles": "build-test-tooling",
            }
        )
    method = {
        "analysis_boundary": (
            "complete package-lock graph; all root package dependencies are "
            "devDependencies and no npm module is shipped in the plain-ES-module UI"
        )
    }
    return sorted(rows, key=lambda row: (row["name"], row["version"])), method


# ---------------------------------------------------------------------------
# CycloneDX, summary, and unknown-license enforcement
# ---------------------------------------------------------------------------


def _component_purl(row: dict[str, Any]) -> str:
    prefix = {"python": "pypi", "rust": "cargo", "npm": "npm"}[row["ecosystem"]]
    return f"pkg:{prefix}/{row['name']}@{row['version']}"


def write_cyclonedx(
    rows: list[dict[str, Any]], ecosystem: str, method: dict[str, Any], path: Path
) -> None:
    components: list[dict[str, Any]] = []
    for row in rows:
        component: dict[str, Any] = {
            "type": "library",
            "name": row["name"],
            "version": row["version"],
            "purl": _component_purl(row),
            "properties": [
                {"name": "omnicovas:distribution", "value": row["distribution"]},
                {"name": "omnicovas:evidence", "value": row["evidence"]},
                {"name": "omnicovas:roles", "value": row["roles"]},
            ],
        }
        if row["license"] != UNKNOWN:
            component["licenses"] = [{"expression": row["license"]}]
        components.append(component)

    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "omnicovas",
                "version": "0.1.0",
            },
            "properties": [
                {"name": "omnicovas:ecosystem", "value": ecosystem},
                {"name": "omnicovas:network-resolution", "value": "none"},
                {
                    "name": "omnicovas:evidence-boundary",
                    "value": str(method["analysis_boundary"]),
                },
            ],
        },
        "components": components,
    }
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _load_allowlist() -> list[dict[str, str]]:
    data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("entries"), list):
        raise RuntimeError(f"Invalid SBOM license allowlist: {ALLOWLIST_PATH}")
    return data["entries"]


def _unknown_disposition(
    row: dict[str, Any], allowlist: list[dict[str, str]]
) -> dict[str, str] | None:
    for entry in allowlist:
        if (
            entry.get("ecosystem") == row["ecosystem"]
            and _normalise(entry.get("name", "")) == _normalise(row["name"])
            and entry.get("version") == row["version"]
            and entry.get("rationale", "").strip()
        ):
            return entry
    return None


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        python_rows, python_method = collect_python()
        rust_rows, rust_method = collect_rust()
        npm_rows, npm_method = collect_npm()
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"SBOM generation failed: {exc}", file=sys.stderr)
        return 1

    write_cyclonedx(
        python_rows,
        "python",
        python_method,
        OUT_DIR / "python-sbom-cyclonedx.json",
    )
    write_cyclonedx(
        rust_rows, "rust", rust_method, OUT_DIR / "rust-sbom-cyclonedx.json"
    )
    write_cyclonedx(npm_rows, "npm", npm_method, OUT_DIR / "npm-sbom-cyclonedx.json")

    all_rows = python_rows + rust_rows + npm_rows
    fieldnames = [
        "ecosystem",
        "name",
        "version",
        "license",
        "distribution",
        "direct",
        "evidence",
        "roles",
    ]
    with (OUT_DIR / "dependency-license-inventory.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    allowlist = _load_allowlist()
    unknown: list[dict[str, Any]] = []
    unallowlisted: list[dict[str, Any]] = []
    for row in all_rows:
        if row["license"] != UNKNOWN:
            continue
        disposition = _unknown_disposition(row, allowlist)
        record = {
            "ecosystem": row["ecosystem"],
            "name": row["name"],
            "version": row["version"],
            "distribution": row["distribution"],
            "allowlisted_disposition": disposition,
        }
        unknown.append(record)
        if disposition is None:
            unallowlisted.append(record)

    summary: dict[str, Any] = {
        "schema_version": 2,
        "release_target": TARGET_TRIPLE,
        "evidence_methods": {
            "python": python_method,
            "rust": rust_method,
            "npm": npm_method,
        },
        "ecosystems": {},
        "unknown": unknown,
        "unallowlisted_unknown": unallowlisted,
    }
    for ecosystem, rows in (
        ("python", python_rows),
        ("rust", rust_rows),
        ("npm", npm_rows),
    ):
        distribution_counts = Counter(row["distribution"] for row in rows)
        ecosystem_unknown = [row for row in rows if row["license"] == UNKNOWN]
        summary["ecosystems"][ecosystem] = {
            "total": len(rows),
            "known_license_metadata": len(rows) - len(ecosystem_unknown),
            "unknown_license_metadata": len(ecosystem_unknown),
            "release_components": sum(
                1 for row in rows if row["distribution"] in RELEASE_DISTRIBUTIONS
            ),
            "non_release_components": sum(
                1 for row in rows if row["distribution"] not in RELEASE_DISTRIBUTIONS
            ),
            "distribution_classes": dict(sorted(distribution_counts.items())),
        }
    summary["totals"] = {
        "total": len(all_rows),
        "known_license_metadata": sum(
            1 for row in all_rows if row["license"] != UNKNOWN
        ),
        "unknown_license_metadata": len(unknown),
        "unallowlisted_unknown_license_metadata": len(unallowlisted),
        "release_components": sum(
            1 for row in all_rows if row["distribution"] in RELEASE_DISTRIBUTIONS
        ),
        "non_release_components": sum(
            1 for row in all_rows if row["distribution"] not in RELEASE_DISTRIBUTIONS
        ),
    }
    summary["license_histogram"] = dict(
        Counter(row["license"] for row in all_rows).most_common()
    )
    (OUT_DIR / "inventory-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    evidence_files = (
        "python-sbom-cyclonedx.json",
        "rust-sbom-cyclonedx.json",
        "npm-sbom-cyclonedx.json",
        "dependency-license-inventory.csv",
        "inventory-summary.json",
    )
    manifest = {
        "schema_version": 1,
        "release_target": TARGET_TRIPLE,
        "generation_command": (
            ".venv/Scripts/python.exe scripts/release/generate_sbom_inventory.py"
        ),
        "files": {
            name: hashlib.sha256((OUT_DIR / name).read_bytes()).hexdigest()
            for name in evidence_files
        },
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "license_allowlist_sha256": hashlib.sha256(
            ALLOWLIST_PATH.read_bytes()
        ).hexdigest(),
    }
    (OUT_DIR / "sbom-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(json.dumps(summary["totals"], indent=2))
    print("\nPer ecosystem:")
    print(json.dumps(summary["ecosystems"], indent=2))
    if unallowlisted:
        print("\nUnallowlisted unknown-license metadata:", file=sys.stderr)
        print(json.dumps(unallowlisted, indent=2), file=sys.stderr)
        return 2
    if unknown:
        print("\nAllowlisted unknown-license metadata:")
        print(json.dumps(unknown, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
