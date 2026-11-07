"""Render reproducible third-party notices from the Phase 10 inventory.

The output reports evidence classifications exactly as generated. It does not
convert metadata completeness into a legal-compliance conclusion.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from omnicovas.features import exobiology_evidence, galactic_knowledge  # noqa: E402

EVIDENCE = ROOT / "artifacts" / "sbom" / "phase10-reconciliation"
INVENTORY = EVIDENCE / "dependency-license-inventory.csv"
SUMMARY = EVIDENCE / "inventory-summary.json"
OUTPUT = ROOT / "THIRD_PARTY_NOTICES.md"

RELEASE_CLASSES = {
    "packaged-runtime",
    "packaged-development-tool",
    "packaged-implicit-import",
    "release-runtime-graph",
}
REVIEW_KEYWORDS = ("GPL", "AGPL", "LGPL", "MPL", "CDDL", "EPL", "SSPL", "BUSL")


def _table_row(row: dict[str, str]) -> str:
    return (
        f"| `{row['name']}` | {row['version']} | {row['ecosystem']} "
        f"| {row['distribution']} | {row['license']} |"
    )


def main() -> int:
    rows = list(csv.DictReader(INVENTORY.open(encoding="utf-8")))
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    release_candidates = [row for row in rows if row["distribution"] in RELEASE_CLASSES]
    non_release = [row for row in rows if row not in release_candidates]
    review = [
        row
        for row in release_candidates
        if any(keyword in row["license"].upper() for keyword in REVIEW_KEYWORDS)
    ]
    classes: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        classes[row["ecosystem"]][row["distribution"]] += 1

    lines: list[str] = []
    add = lines.append
    add("# Third-Party Notices")
    add("")
    add(
        "OmniCOVAS includes or uses third-party software. Each component remains "
        "subject to its own license terms. This record reports dependency metadata "
        "and packaging/build-graph evidence; it is not legal advice or a conclusion "
        "that every distribution obligation has been discharged."
    )
    add("")
    add("- **Application version:** 0.1.0")
    add("- **Release target:** `x86_64-pc-windows-msvc`")
    add(
        "- **Durable machine-readable evidence:** `sbom/` in a prepared release "
        "directory and the exact-commit CI artifact named "
        "`phase10-candidate-evidence-<commit>`."
    )
    add(
        "- **Source evidence:** installed Python metadata plus PyInstaller analysis, "
        "Cargo resolved dependency graphs, and the complete npm lock graph."
    )
    add("")
    add("## Evidence boundaries")
    add("")
    add(
        "A `packaged-*` Python class means the distribution was mapped from modules "
        "in PyInstaller's sidecar analysis. Runtime-closure packages, development "
        "tools pulled in by hooks, and implicit/hidden imports are distinguished. "
        "This is packaging-analysis evidence, not binary introspection."
    )
    add("")
    add(
        "`release-runtime-graph` means a Rust package is reachable through normal "
        "dependencies in Cargo's resolved graph for the Windows release target. It "
        "does not prove that every package or code path remains in the final binary."
    )
    add("")
    add(
        "Build-only, development-only, declared-but-not-observed, and other-target "
        "packages remain in the inventory as conservative legal-review evidence. "
        "They are not described as shipped application components. All npm packages "
        "are build/test tooling: `package.json` has no runtime dependencies and the "
        "UI ships as plain ES modules."
    )
    add("")
    add("## Inventory summary")
    add("")
    totals = summary["totals"]
    add(
        f"The inventory contains **{totals['total']} components**: "
        f"**{totals['release_components']} release-candidate components** and "
        f"**{totals['non_release_components']} retained non-release graph "
        "components**."
    )
    add("")
    add("| Ecosystem | Classification | Components |")
    add("|---|---|---:|")
    for ecosystem in sorted(classes):
        for classification, count in sorted(classes[ecosystem].items()):
            add(f"| {ecosystem} | {classification} | {count} |")
    add("")
    add(
        f"License metadata is present for **{totals['known_license_metadata']}** "
        f"components; **{totals['unknown_license_metadata']}** are unknown and "
        f"**{totals['unallowlisted_unknown_license_metadata']}** are unknown without "
        "an explicit allowlisted disposition. Zero unknown metadata is not a legal "
        "clearance or an assertion that all obligations are satisfied."
    )
    add("")

    add("## Qualified review required before publication")
    add("")
    add(
        "A qualified reviewer must determine the applicable obligations for the "
        "actual release. This includes MPL-2.0 source/notice obligations and an "
        "explicit election for every multi-licensed dependency. This generator "
        "records expressions such as `MIT OR Apache-2.0`; it does not make the "
        "election."
    )
    add("")
    if review:
        add("Metadata expressions containing review keywords in release classes:")
        add("")
        add("| Component | Version | Ecosystem | Evidence class | License |")
        add("|---|---|---|---|---|")
        for row in sorted(review, key=lambda item: (item["ecosystem"], item["name"])):
            add(_table_row(row))
        add("")

    add("## License-expression summary for release classes")
    add("")
    add("| Metadata expression | Components |")
    add("|---|---:|")
    for expression, count in Counter(
        row["license"] for row in release_candidates
    ).most_common():
        add(f"| {expression} | {count} |")
    add("")

    add("## Release-class components")
    add("")
    add("| Component | Version | Ecosystem | Evidence class | License |")
    add("|---|---|---|---|---|")
    for row in sorted(
        release_candidates, key=lambda item: (item["ecosystem"], item["name"].lower())
    ):
        add(_table_row(row))
    add("")
    add("## Retained non-release graph evidence")
    add("")
    add(
        f"The durable inventory retains {len(non_release)} additional components. "
        "See `sbom/dependency-license-inventory.csv` in the release directory or "
        "exact-commit CI evidence artifact for their versions, roles, licenses, and "
        "evidence classifications."
    )
    add("")
    add("## Elite Dangerous and Frontier Developments")
    add("")
    add(
        "OmniCOVAS is an independent, unofficial project. It is not affiliated "
        "with, endorsed by, sponsored by, approved by, or connected to Frontier "
        "Developments plc. Elite Dangerous, Frontier Developments, COVAS, and "
        "related names, marks, and assets belong to their respective owners."
    )
    add("")
    # Credit for the references behind the shipped galactic knowledge packs.
    lines.extend(galactic_knowledge.notice_markdown())
    # Provenance of the independent exobiology journal-evidence asset (FU-021).
    lines.extend(exobiology_evidence.notice_markdown())
    add("## Regeneration")
    add("")
    add("```")
    add(".venv/Scripts/python.exe scripts/release/generate_sbom_inventory.py")
    add(".venv/Scripts/python.exe scripts/release/generate_third_party_notices.py")
    add("```")
    add("")
    add(
        "Regenerate after dependency or packaging-analysis changes. Publication "
        "remains held until the manual legal and release gates are accepted."
    )
    add("")

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")
    print(f"release-class components: {len(release_candidates)}")
    print(f"review-keyword components: {len(review)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
