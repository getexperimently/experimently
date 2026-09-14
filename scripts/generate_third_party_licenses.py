#!/usr/bin/env python3
"""Regenerate THIRD_PARTY_LICENSES.md from what the project actually depends on.

Sources
-------
Python   `pip-licenses` against the active virtualenv, which is installed from
         `backend/requirements.txt` plus `modules/requirements.txt` (the
         module-only pins the full profile adds).
Node     `npx license-checker-rseidelsohn --production` in each package that has
         a `package-lock.json` (the dashboard and the five JavaScript SDKs).
Other    Declared direct dependencies read out of the per-SDK manifests
         (go.mod, pom.xml, build.gradle.kts, composer.json, mix.exs,
         pubspec.yaml, Package.swift, *.csproj). No resolver is run for these
         ecosystems because the repository does not vendor their toolchains;
         the licence column is the upstream project's published licence.

Usage
-----
    source venv/bin/activate
    pip install pip-licenses
    python scripts/generate_third_party_licenses.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "THIRD_PARTY_LICENSES.md"

NODE_PACKAGES = [
    ("frontend", "Dashboard (Next.js)"),
    ("sdk/js", "JavaScript SDK"),
    ("sdk/react", "React SDK"),
    ("sdk/react-native", "React Native SDK"),
    ("sdk/openfeature", "OpenFeature provider (JavaScript)"),
    ("sdk/edge", "Edge SDK"),
]

# Direct dependencies declared in manifests for ecosystems with no resolver here.
MANIFEST_DEPS: dict[str, list[tuple[str, str, str]]] = {
    "Go SDK (`sdk/go/go.mod`)": [
        ("(standard library only)", "—", "BSD-3-Clause (Go standard library)"),
    ],
    "Java SDK (`sdk/java/*/pom.xml`)": [
        ("com.squareup.okhttp3:okhttp", "4.12.0", "Apache-2.0"),
        ("com.fasterxml.jackson.core:jackson-databind", "see pom", "Apache-2.0"),
        ("org.springframework.boot:spring-boot-dependencies", "see pom", "Apache-2.0"),
        ("org.junit.jupiter:junit-jupiter (test)", "see pom", "EPL-2.0"),
        ("org.mockito:mockito-core (test)", "see pom", "MIT"),
        ("com.squareup.okhttp3:mockwebserver (test)", "4.12.0", "Apache-2.0"),
    ],
    "Android SDK (`sdk/android/sdk/build.gradle.kts`)": [
        ("com.squareup.okhttp3:okhttp", "4.12.0", "Apache-2.0"),
        ("org.jetbrains.kotlinx:kotlinx-coroutines-android", "1.7.3", "Apache-2.0"),
        ("org.jetbrains.kotlinx:kotlinx-serialization-json", "1.6.2", "Apache-2.0"),
        ("junit:junit (test)", "4.13.2", "EPL-1.0"),
        ("org.junit.jupiter:junit-jupiter (test)", "5.10.1", "EPL-2.0"),
        ("com.squareup.okhttp3:mockwebserver (test)", "4.12.0", "Apache-2.0"),
        ("org.json:json (test)", "20240303", "Public Domain"),
        ("io.mockk:mockk (test)", "1.13.9", "Apache-2.0"),
        ("org.assertj:assertj-core (test)", "3.24.2", "Apache-2.0"),
    ],
    "iOS SDK (`sdk/ios/Package.swift`)": [
        (
            "(no external package dependencies; Foundation + CommonCrypto)",
            "—",
            "Apple SDK terms",
        ),
    ],
    "Flutter SDK (`sdk/flutter/pubspec.yaml`)": [
        ("http", "^1.1.0", "BSD-3-Clause"),
        ("shared_preferences", "^2.2.0", "BSD-3-Clause"),
        ("crypto", "^3.0.3", "BSD-3-Clause"),
    ],
    "PHP SDK (`sdk/php/composer.json`)": [
        ("php (ext-json, ext-curl)", ">=8.1", "PHP-3.01 / runtime, not bundled"),
        ("phpunit/phpunit (dev)", "^10.0", "BSD-3-Clause"),
    ],
    "Ruby SDK (`sdk/ruby/experimently.gemspec`)": [
        ("(standard library only)", "—", "Ruby / BSD-2-Clause"),
    ],
    "Elixir SDK (`sdk/elixir/mix.exs`)": [
        ("jason", "~> 1.4", "Apache-2.0"),
        ("ex_doc (dev)", "~> 0.31", "Apache-2.0"),
    ],
    ".NET SDK (`sdk/dotnet/**/*.csproj`)": [
        ("System.Text.Json", "8.0.5", "MIT"),
        ("xunit (test)", "2.6.6", "Apache-2.0"),
        ("Microsoft.NET.Test.Sdk (test)", "17.8.0", "MIT"),
        ("coverlet.collector (test)", "6.0.0", "MIT"),
    ],
    "Python SDKs (`sdk/python`, `sdk/openfeature-python`)": [
        ("(experimently: standard library only)", "—", "—"),
        ("openfeature-sdk", ">=0.9.0", "Apache-2.0"),
    ],
}

# Licences that need a human decision before they ship in an Apache-2.0 work.
#
# This project is Apache-2.0, a permissive licence: a dependency is a problem
# when its own terms would reach the combined work.  Strong copyleft (GPL,
# AGPL) does exactly that -- a GPL library in the runtime closure would bind
# the distribution to the GPL, and the AGPL adds the network-use clause on
# top -- so those two are the ones to keep out.  Weak copyleft (LGPL, MPL,
# EPL, CDDL) only reaches the library itself: linking an unmodified copy is
# fine, modifications to the library must be published under its licence.
# psycopg2-binary (LGPL) is the standing example and is deliberately allowed.
#
# Matched as whole licence identifiers, not substrings.  A plain
# `"GPL" in lic.lower()` reports LGPL and AGPL as plain GPL and gives them the
# wrong note; the lookbehind keeps `GPL` from matching inside `LGPL`/`AGPL`,
# and the list is ordered most specific first so the right note wins.
COPYLEFT_FLAGS: list[tuple[str, str]] = [
    (
        r"(?<![A-Z])AGPL",
        "strong copyleft with a network-use clause — binds the combined work; "
        "must not ship in the runtime closure of an Apache-2.0 product",
    ),
    (
        r"(?<![A-Z])LGPL",
        "weak copyleft — linking an unmodified copy is fine; modifications "
        "to the library must be published under the LGPL",
    ),
    (
        r"(?<![A-Z])GPL",
        "strong copyleft — binds the combined work; must not ship in the "
        "runtime closure of an Apache-2.0 product",
    ),
    ("SSPL", "NOT an open-source licence; must not ship"),
    ("BUSL", "source-available, not open source; must not ship"),
    ("Elastic", "source-available, not open source; must not ship"),
    ("CC-BY-SA", "share-alike — unusable for code; data only, and it stays CC-BY-SA"),
    ("CC-BY-NC", "non-commercial, unusable"),
    (
        "CDDL",
        "file-level weak copyleft — combining is fine; modified files stay CDDL",
    ),
    (
        "EPL-1.0",
        "module-level weak copyleft — fine as a separate artefact; "
        "modifications to it stay EPL",
    ),
    (
        "MS-PL",
        "permissive but source redistributions of the library must stay MS-PL; "
        "keep it a separate artefact",
    ),
    ("UNKNOWN", "licence could not be determined — must be resolved by hand"),
    ("UNLICENSED", "no licence declared"),
]

_COPYLEFT_PATTERNS = [
    (re.compile(pattern, re.IGNORECASE), why) for pattern, why in COPYLEFT_FLAGS
]


def run(cmd: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(
        cmd, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


#: Every pinned dependency of the product. The module-only pins live in their
#: own file -- only the full profile installs them -- and they are as much a
#: redistributed dependency as the rest, so both files are read. The second is
#: absent in a core checkout.
REQUIREMENTS = [
    ROOT / "backend" / "requirements.txt",
    ROOT / "modules" / "requirements.txt",
]


def _canonical(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def declared_python_dependencies() -> set[str]:
    """The transitive closure of the pins in the requirements files.

    Whatever else happens to be installed in the virtualenv the generator
    runs in -- a formatter that was replaced, a tool tried once -- is not a
    dependency of the product and must not appear in a legal document that
    says it lists the product's dependencies.  Closed over ``Requires-Dist``
    with the environment's markers, extras included when the pin asks for
    them.
    """
    from importlib import metadata

    from packaging.requirements import Requirement

    roots: list[Requirement] = []
    for path in REQUIREMENTS:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith(("-", "git+")):
                continue
            try:
                roots.append(Requirement(line))
            except Exception:
                continue

    closure: set[str] = set()
    pending = list(roots)
    while pending:
        req = pending.pop()
        name = _canonical(req.name)
        if name in closure:
            continue
        try:
            dist = metadata.distribution(req.name)
        except metadata.PackageNotFoundError:
            continue  # not installed here: nothing to report, nothing to walk
        closure.add(name)
        for spec in dist.requires or ():
            child = Requirement(spec)
            if child.marker is not None:
                env = {"extra": ""}
                wanted = any(
                    child.marker.evaluate({"extra": extra}) for extra in req.extras
                ) or child.marker.evaluate(env)
                if not wanted:
                    continue
            pending.append(child)
    return closure


def python_rows() -> list[tuple[str, str, str]]:
    raw = json.loads(run([sys.executable, "-m", "piplicenses", "--format=json"]))
    declared = declared_python_dependencies()
    rows = []
    for pkg in raw:
        name = pkg["Name"]
        if _canonical(name) not in declared:
            continue
        rows.append((name, pkg["Version"], normalise(pkg["License"])))
    return rows


def node_rows(pkg_dir: str) -> list[tuple[str, str, str]]:
    out = run(
        [
            "npx",
            "--yes",
            "license-checker-rseidelsohn",
            "--production",
            "--json",
            # The scanned package itself is `private: true`, which the checker
            # reports as UNLICENSED; it is not a third party.
            "--excludePrivatePackages",
        ],
        cwd=ROOT / pkg_dir,
    )
    data = json.loads(out)
    rows = []
    for key, val in data.items():
        name, _, version = key.rpartition("@")
        lic = val.get("licenses")
        if isinstance(lic, list):
            lic = " OR ".join(lic)
        rows.append((name or key, version, normalise(str(lic))))
    return rows


def normalise(lic: str) -> str:
    table = {
        "MIT License": "MIT",
        "Apache Software License": "Apache-2.0",
        "Apache 2.0": "Apache-2.0",
        "Apache License 2.0": "Apache-2.0",
        "BSD License": "BSD",
        "3-Clause BSD License": "BSD-3-Clause",
        "ISC License (ISCL)": "ISC",
        "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
        "GNU Library or Lesser General Public License (LGPL)": "LGPL",
        "Python Software Foundation License": "PSF-2.0",
        "The Unlicense (Unlicense)": "Unlicense",
        "MIT License; MIT No Attribution License (MIT-0)": "MIT OR MIT-0",
        "Apache Software License; MIT License": "Apache-2.0 OR MIT",
        "Apache Software License; BSD License": "Apache-2.0 OR BSD",
    }
    return table.get(lic.strip(), lic.strip())


def flags_for(lic: str) -> str | None:
    """The note for the first flagged licence named in *lic*, or None.

    *lic* may be an expression ("Apache-2.0 OR MIT", "GPL-2.0 WITH
    Classpath-exception-2.0"), so this looks for identifiers inside it rather
    than comparing the whole string.
    """
    for pattern, why in _COPYLEFT_PATTERNS:
        if pattern.search(lic):
            return why
    return None


def grouped_table(rows: list[tuple[str, str, str]]) -> str:
    by_lic: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for name, version, lic in rows:
        by_lic[lic].append((name, version))
    lines = []
    for lic in sorted(by_lic, key=lambda k: (-len(by_lic[k]), k)):
        flag = flags_for(lic)
        header = f"#### {lic} ({len(by_lic[lic])})"
        if flag:
            header += f"  ⚠️ {flag}"
        lines.append(header)
        lines.append("")
        lines.append("| Package | Version |")
        lines.append("|---|---|")
        for name, version in sorted(by_lic[lic]):
            lines.append(f"| `{name}` | {version} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parts: list[str] = []
    parts.append(
        f"""# Third-party licences

Generated by `scripts/generate_third_party_licenses.py` on {date.today().isoformat()}.
Do not edit by hand; re-run the script after a dependency change.

Experimently's own licensing is in `LICENSE` (Apache-2.0, the whole repository
including the optional modules) and `sdk/LICENSE` (MIT, the client SDKs). This
file covers only third-party software: what the product depends on, and under
which licence each dependency is redistributed.

Sections are grouped by licence, most common first. A ⚠️ marks a licence that
needs a human decision before redistribution — for an Apache-2.0 product that
is strong copyleft (GPL, AGPL), which must not ship in the runtime closure,
and weak copyleft (LGPL, MPL, EPL, CDDL), which is fine to link unmodified.
"""
    )

    parts.append("## Python — backend, Lambda functions, infrastructure\n")
    parts.append(
        "The transitive closure of the pins in `backend/requirements.txt` "
        "(runtime, test and CDK pins together) and `modules/requirements.txt` "
        "(the module-only pins the full profile installs), with versions and "
        "licences read from the installed distributions by `pip-licenses`. "
        "Packages that happen to be installed but are not reachable from a pin "
        "are not dependencies and are not listed.\n"
    )
    parts.append(grouped_table(python_rows()))

    for pkg_dir, label in NODE_PACKAGES:
        parts.append(f"## Node — {label} (`{pkg_dir}`)\n")
        parts.append("Resolved with `license-checker-rseidelsohn --production`.\n")
        parts.append(grouped_table(node_rows(pkg_dir)))

    parts.append("## Other SDK ecosystems — declared direct dependencies\n")
    parts.append(
        "These ecosystems have no resolver in this repository, so the list below "
        "is read from the manifests and the licence column is the upstream "
        "project's published licence. Regenerate by hand when a manifest changes.\n"
    )
    for label, deps in MANIFEST_DEPS.items():
        parts.append(f"### {label}\n")
        parts.append("| Package | Version | Licence |")
        parts.append("|---|---|---|")
        for name, version, lic in deps:
            flag = flags_for(lic)
            suffix = f" ⚠️ {flag}" if flag else ""
            parts.append(f"| `{name}` | {version} | {lic}{suffix} |")
        parts.append("")

    OUT.write_text("\n".join(parts) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
