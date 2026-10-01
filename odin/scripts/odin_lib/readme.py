"""Repository README support: technology discovery and formatting enforcement.

Two jobs, both mechanical:

``scan``  sweeps the inventory for the manifests, configuration, CI, container,
          IaC, entrypoint, test and documentation evidence a README must be built
          from, ranks the languages, and proposes a component map.

``lint``  enforces the README formatting constraints that break real renderers:
          emoji and ampersands in headings, forbidden Unicode ranges anywhere,
          required section order, and table-of-contents anchors that resolve.

Neither writes the README. Prose is the agent's job; this module supplies the
evidence and then checks the result.
"""

from __future__ import annotations

import re
import unicodedata

from .common import read_json, read_jsonl, write_json

# --------------------------------------------------------------------------
# discovery tables
# --------------------------------------------------------------------------

ECOSYSTEMS = [
    ("dotnet", ".NET", [
        r"\.sln$", r"\.csproj$", r"\.fsproj$", r"\.vbproj$", r"^Directory\.Build\.(props|targets)$",
        r"^global\.json$", r"^NuGet\.config$", r"\.vcxproj$"]),
    ("node", "Node / JavaScript / TypeScript", [
        r"^package\.json$", r"^pnpm-lock\.yaml$", r"^yarn\.lock$", r"^package-lock\.json$",
        r"^tsconfig.*\.json$", r"^nx\.json$", r"^turbo\.json$", r"^bun\.lockb?$", r"^deno\.jsonc?$"]),
    ("python", "Python", [
        r"^pyproject\.toml$", r"^requirements.*\.txt$", r"^setup\.py$", r"^setup\.cfg$",
        r"^Pipfile$", r"^poetry\.lock$", r"^uv\.lock$", r"^pdm\.lock$", r"^environment\.ya?ml$",
        r"^tox\.ini$", r"^noxfile\.py$"]),
    ("jvm", "Java / Kotlin", [
        r"^pom\.xml$", r"^build\.gradle(\.kts)?$", r"^settings\.gradle(\.kts)?$",
        r"^gradlew(\.bat)?$", r"^gradle\.properties$", r"^mvnw(\.cmd)?$"]),
    ("go", "Go", [r"^go\.mod$", r"^go\.sum$", r"^go\.work$"]),
    ("rust", "Rust", [r"^Cargo\.toml$", r"^Cargo\.lock$"]),
    ("ruby", "Ruby", [r"^Gemfile$", r"^Gemfile\.lock$", r"\.gemspec$", r"^Rakefile$"]),
    ("php", "PHP", [r"^composer\.json$", r"^composer\.lock$"]),
    ("cpp", "C / C++", [r"^CMakeLists\.txt$", r"^Makefile$", r"^meson\.build$", r"^configure\.ac$"]),
    ("mobile", "Mobile", [r"^AndroidManifest\.xml$", r"\.xcodeproj$", r"\.xcworkspace$",
                          r"^Podfile$", r"^pubspec\.yaml$"]),
    ("frontend", "Frontend framework", [
        r"^next\.config\..*$", r"^vite\.config\..*$", r"^angular\.json$", r"^vue\.config\..*$",
        r"^svelte\.config\..*$", r"^remix\.config\..*$", r"^nuxt\.config\..*$",
        r"^astro\.config\..*$"]),
    ("monorepo", "Monorepo tooling", [
        r"^lerna\.json$", r"^pnpm-workspace\.yaml$", r"^rush\.json$",
        r"^WORKSPACE(\.bazel)?$", r"^MODULE\.bazel$", r"^BUCK$", r"^pants\.toml$"]),
    ("elixir", "Elixir / Erlang", [r"^mix\.exs$", r"^mix\.lock$", r"^rebar\.config$"]),
    ("swift", "Swift", [r"^Package\.swift$", r"^Package\.resolved$"]),
    ("zig", "Zig", [r"^build\.zig$", r"^build\.zig\.zon$"]),
    ("haskell", "Haskell", [r"^stack\.yaml$", r"\.cabal$", r"^cabal\.project$"]),
    ("ocaml", "OCaml", [r"^dune-project$", r"\.opam$"]),
    ("nix", "Nix", [r"^flake\.nix$", r"^default\.nix$", r"^shell\.nix$"]),
    ("terraform", "Terraform / OpenTofu", [r"\.tf$", r"^\.terraform\.lock\.hcl$"]),
    ("bazel", "Bazel", [
        r"^BUILD(\.bazel)?$", r"^WORKSPACE(\.bazel)?$", r"^MODULE\.bazel$"]),
    ("julia", "Julia", [r"^Project\.toml$", r"^Manifest\.toml$"]),
    ("r", "R", [r"^DESCRIPTION$", r"^renv\.lock$"]),
]

CI_PATTERNS = [
    (r"^\.github/workflows/", "GitHub Actions"),
    (r"^azure-pipelines.*\.ya?ml$", "Azure Pipelines"),
    (r"^Jenkinsfile", "Jenkins"),
    (r"^\.gitlab-ci\.ya?ml$", "GitLab CI"),
    (r"^\.circleci/", "CircleCI"),
    (r"^\.buildkite/", "Buildkite"),
    (r"^\.drone\.ya?ml$", "Drone"),
    (r"^appveyor\.ya?ml$", "AppVeyor"),
    (r"^cloudbuild\.ya?ml$", "Google Cloud Build"),
    (r"^buildspec\.ya?ml$", "AWS CodeBuild"),
    (r"^\.woodpecker", "Woodpecker CI"),
    (r"^teamcity", "TeamCity"),
]

CONTAINER_IAC_PATTERNS = [
    (r"(^|/)Dockerfile", "Dockerfile"),
    (r"(^|/)Containerfile", "Containerfile"),
    (r"(^|/)(docker-)?compose.*\.ya?ml$", "Compose"),
    (r"(^|/)Chart\.ya?ml$", "Helm chart"),
    (r"(^|/)kustomization\.ya?ml$", "Kustomize"),
    (r"\.tf$|\.tfvars$", "Terraform / OpenTofu"),
    (r"\.bicep$", "Bicep"),
    (r"(^|/)Pulumi\.ya?ml$", "Pulumi"),
    (r"(^|/)(template|serverless)\.ya?ml$", "Serverless / CloudFormation"),
    (r"(^|/)k8s/|(^|/)kubernetes/|(^|/)manifests/", "Kubernetes manifests"),
]

CONFIG_PATTERNS = [
    (r"^appsettings.*\.json$", "ASP.NET settings"),
    (r"^web\.config$", "web.config"),
    (r"^\.env(\..*)?$", "Environment file"),
    (r"(^|/)config/", "config directory"),
    (r"\.(ini|cfg|conf|properties|toml)$", "configuration file"),
]

SECRET_MANAGER_HINTS = [
    (r"(?i)\bhashicorp\b|\bvault\b", "HashiCorp Vault"),
    (r"(?i)secretsmanager|aws_secret|SSM Parameter|ssm:", "AWS Secrets Manager / SSM"),
    (r"(?i)azure[ _-]?key[ _-]?vault", "Azure Key Vault"),
    (r"(?i)google[ _-]?secret[ _-]?manager|gcp[ _-]?secret", "GCP Secret Manager"),
    (r"(?i)\bdoppler\b", "Doppler"),
    (r"(?i)1password|op://", "1Password"),
]

TEST_FRAMEWORKS = [
    (r"(?i)\bxunit\b", "xUnit"), (r"(?i)\bnunit\b", "NUnit"), (r"(?i)\bmstest\b", "MSTest"),
    (r"(?i)\bjest\b", "Jest"), (r"(?i)\bvitest\b", "Vitest"), (r"(?i)\bmocha\b", "Mocha"),
    (r"(?i)\bpytest\b", "pytest"), (r"(?i)\bunittest\b", "unittest"),
    (r"(?i)\bjunit\b", "JUnit"), (r"(?i)\btestify\b", "testify"),
    (r"(?i)\bcypress\b", "Cypress"), (r"(?i)\bplaywright\b", "Playwright"),
    (r"(?i)\brspec\b", "RSpec"), (r"(?i)\bphpunit\b", "PHPUnit"),
]

# Manifests and build files are also matched by path, not only by inventory
# role_hint. Classification assigns .sln/.csproj/Directory.Build.props the
# "first-party-source" role, so a role-only query reported no_manifests=true for
# a repository full of .NET manifests.
MANIFEST_PATTERNS = [
    (r"\.slnx?$", ".NET solution"),
    (r"\.(cs|fs|vb)proj$", ".NET project"),
    (r"(^|/)Directory\.Build\.(props|targets)$", "MSBuild directory build file"),
    (r"(^|/)Directory\.Packages\.props$", "NuGet central package management"),
    (r"(^|/)global\.json$", ".NET SDK pin"),
    (r"(?i)(^|/)nuget\.config$", "NuGet configuration"),
    (r"(^|/)packages\.lock\.json$", "NuGet lockfile"),
    (r"(^|/)package\.json$", "npm manifest"),
    (r"(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock)$", "npm lockfile"),
    (r"(^|/)pyproject\.toml$", "Python project"),
    (r"(^|/)requirements[^/]*\.txt$", "Python requirements"),
    (r"(^|/)(setup\.py|setup\.cfg|Pipfile|Pipfile\.lock|poetry\.lock)$", "Python manifest or lockfile"),
    (r"(^|/)pom\.xml$", "Maven manifest"),
    (r"(^|/)(build|settings)\.gradle(\.kts)?$", "Gradle build"),
    (r"(^|/)go\.(mod|sum)$", "Go module"),
    (r"(^|/)Cargo\.(toml|lock)$", "Cargo manifest or lockfile"),
    (r"(^|/)Gemfile(\.lock)?$", "Bundler manifest or lockfile"),
    (r"(^|/)composer\.(json|lock)$", "Composer manifest or lockfile"),
]

BUILD_PATTERNS = [
    (r"(^|/)Makefile$", "Makefile"),
    (r"(^|/)CMakeLists\.txt$", "CMake"),
    (r"(^|/)gradlew(\.bat)?$", "Gradle wrapper"),
    (r"(^|/)BUILD(\.bazel)?$", "Bazel"),
]

ENTRYPOINT_PATTERNS = [
    (r"(^|/)(main|Main)\.(py|go|rs|c|cpp|java|kt)$", "conventional main module"),
    (r"(^|/)Program\.cs$", ".NET program entrypoint"),
    (r"(^|/)Startup\.cs$", "ASP.NET startup"),
    (r"(^|/)__main__\.py$", "Python package entrypoint"),
    (r"(^|/)(index|app|server)\.(js|ts|mjs|cjs)$", "Node entrypoint"),
    (r"(^|/)manage\.py$", "Django management entrypoint"),
    (r"(^|/)wsgi\.py$|(^|/)asgi\.py$", "WSGI/ASGI entrypoint"),
    (r"(^|/)cmd/[^/]+/main\.go$", "Go command entrypoint"),
    (r"(^|/)src/main\.rs$|(^|/)src/bin/", "Rust binary entrypoint"),
]

DOC_PATTERNS = [
    (r"^docs?/", "docs directory"),
    (r"^wiki/", "wiki directory"),
    (r"(^|/)adr/|(^|/)decisions/", "architecture decision records"),
    (r"(^|/)rfcs?/", "RFCs"),
    (r"\.(mmd|puml|drawio)$", "diagram source"),
]


def _matches(patterns, path):
    for pattern, label in patterns:
        if re.search(pattern, path):
            return label
    return None


def scan(state):
    """Sweep the inventory for README evidence. Writes readme/component-map.json."""
    packet = state.packet_root
    rows = read_jsonl(packet / "inventory" / "files.jsonl")
    regular = [r for r in rows if r.get("entry_type") == "regular-file"]
    project = [r for r in regular
               if r.get("origin_hint") not in ("vcs-metadata", "vendored")]

    langs = {}
    for r in project:
        label = r.get("classification_primary")
        if not label:
            continue
        bucket = langs.setdefault(label, {"files": 0, "lines": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["lines"] += int(r.get("line_count") or 0)
        bucket["bytes"] += int(r.get("size_bytes") or 0)
    ranked = sorted(langs.items(), key=lambda kv: (-kv[1]["lines"], -kv[1]["files"], kv[0]))

    ecosystems = {}
    for r in project:
        name = r["path"].rsplit("/", 1)[-1]
        for key, label, patterns in ECOSYSTEMS:
            for pattern in patterns:
                if re.search(pattern, name) or re.search(pattern, r["path"]):
                    ecosystems.setdefault(key, {"label": label, "evidence": []})
                    if r["path"] not in ecosystems[key]["evidence"]:
                        ecosystems[key]["evidence"].append(r["path"])
                    break

    def collect(patterns):
        found = {}
        for r in project:
            label = _matches(patterns, r["path"])
            if label:
                found.setdefault(label, []).append(r["path"])
        return {k: sorted(v)[:40] for k, v in sorted(found.items())}

    ci = collect(CI_PATTERNS)
    containers = collect(CONTAINER_IAC_PATTERNS)
    config = collect(CONFIG_PATTERNS)
    entrypoints = collect(ENTRYPOINT_PATTERNS)
    docs = collect(DOC_PATTERNS)

    manifest_roles = {"package-manifest", "lockfile"}
    def collect_paths(patterns):
        return [r["path"] for r in project if _matches(patterns, r["path"])]

    # Union the role-derived set with path matching: classification labels .NET
    # manifests as first-party source, so role_hint alone under-reports them.
    manifests = sorted(set(r["path"] for r in project if r.get("role_hint") in manifest_roles)
                       | set(collect_paths(MANIFEST_PATTERNS)))
    tests = sorted(r["path"] for r in project if r.get("role_hint") == "test")
    build = sorted(set(r["path"] for r in project if r.get("role_hint") == "build")
                   | set(collect_paths(BUILD_PATTERNS)))

    # Test frameworks, from manifest and test-file content.
    frameworks = set()
    repo_root = state.repo_root
    for rel in (manifests + tests)[:200]:
        candidate = repo_root / rel
        try:
            if candidate.is_file() and candidate.stat().st_size < 1_000_000:
                blob = candidate.read_text(encoding="utf-8", errors="replace")
            else:
                continue
        except OSError:
            continue
        for pattern, label in TEST_FRAMEWORKS:
            if re.search(pattern, blob):
                frameworks.add(label)

    secret_managers = set()
    for r in project[:500]:
        if r.get("content_kind") != "text" or int(r.get("size_bytes") or 0) > 1_000_000:
            continue
        try:
            blob = (repo_root / r["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern, label in SECRET_MANAGER_HINTS:
            if re.search(pattern, blob):
                secret_managers.add(label)

    # Proposed components, from module registry if present, else top-level dirs.
    registry = read_json(packet / "inventory" / "modules.json")
    if registry and registry.get("modules"):
        components = [{
            "name": m.get("name") or m["id"],
            "id": m["id"],
            "path": m["path"],
            "type": m.get("kind", "unknown"),
            "file_count": m.get("file_count"),
            "purpose": m.get("purpose", ""),
            "source": "inventory/modules.json",
        } for m in registry["modules"]]
    else:
        tops = {}
        for r in project:
            top = r["path"].split("/")[0] if "/" in r["path"] else "."
            tops[top] = tops.get(top, 0) + 1
        components = [{"name": k, "id": k, "path": k, "type": "unknown",
                       "file_count": v, "purpose": "",
                       "source": "top-level directory (no module registry yet)"}
                      for k, v in sorted(tops.items())]

    if len(components) <= 1:
        shape = "single application or library"
    elif len(ecosystems) > 1 or any(k in ecosystems for k in ("monorepo",)):
        shape = "monorepo with multiple packages"
    else:
        shape = "multi-component system"

    report = {
        "note": "Mechanical sweep of the inventory. Evidence for a README, not prose "
                "for one. Confirm each item before asserting it.",
        "repository_shape": shape,
        "languages_ranked": [{"language": k, **v} for k, v in ranked],
        "ecosystems_detected": ecosystems,
        "components_proposed": components,
        "entrypoints": entrypoints,
        "build_files": build,
        "manifests_and_lockfiles": manifests,
        "ci": ci,
        "containers_and_iac": containers,
        "configuration": config,
        "configuration_note": "Config keys and environment variable names may be "
                              "documented; values must never be printed.",
        "secret_manager_references": sorted(secret_managers),
        "tests": {"files": tests, "frameworks_detected": sorted(frameworks)},
        "documentation": docs,
        "absences": {
            "no_ci": not ci,
            "no_containers_or_iac": not containers,
            "no_tests": not tests,
            "no_manifests": not manifests,
            "note": "An absence is evidence too. Say 'no CI configuration exists' "
                    "rather than omitting the section.",
        },
    }
    write_json(packet / "readme" / "component-map.json", report)
    return report


# --------------------------------------------------------------------------
# lint
# --------------------------------------------------------------------------

FORBIDDEN_RANGES = [
    (0x2500, 0x257F, "Box Drawing"),
    (0x2190, 0x21FF, "Arrows"),
    (0x25A0, 0x25FF, "Geometric Shapes"),
    (0x2300, 0x23FF, "Miscellaneous Technical"),
]

REQUIRED_SECTIONS = [
    "The Rundown",
    "Last Updated",
    "Table of Contents",
    "Repository Overview",
    "Components",
    "Architecture Overview",
    "Tech Stack and Dependencies",
    "Project Layout",
    "Getting Started",
    "Configuration",
    "Running the System",
    "Deployment and CI/CD",
    "Deep Code Reference",
    "Data and Integrations",
    "Security Notes",
    "Observability and Monitoring",
    "Common Tasks and Troubleshooting",
    "Change Log",
    "Contributing",
]

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
MD_LINK = re.compile(r"\[[^\]]*\]\(#([^)]+)\)")
EMOJI_SHORTCODE = re.compile(r":[a-z0-9_+-]{2,}:")


def _is_emoji(ch: str) -> bool:
    code = ord(ch)
    if code < 0x80:
        return False
    if unicodedata.category(ch) == "So":
        return True
    return (
        0x1F000 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or code in (0xFE0F, 0x20E3)
        or 0x1F1E6 <= code <= 0x1F1FF
    )


def slugify(heading: str) -> str:
    """GitHub's heading-to-anchor transformation."""
    text = heading.strip().lower()
    text = re.sub(r"[`*_~]", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "-", text.strip())


def lint(text: str, path_label: str = "README.md", require_sections: bool = True):
    """Check a README against the formatting constraints. Returns a report dict."""
    lines = text.split("\n")
    violations = []
    headings = []

    for ch, name in (("\u2014", "em dash"), ("\u2013", "en dash")):
        if ch in text:
            violations.append({
                "rule": "prose-dash", "severity": "error",
                "detail": name + " found in generated README",
                "fix": "use a comma, colon, period, parentheses, or plain hyphen instead",
            })

    in_fence = False
    fence_marker = None
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence, fence_marker = False, None
            continue

        # Forbidden Unicode applies everywhere, fenced blocks included.
        for column, ch in enumerate(line, start=1):
            code = ord(ch)
            for low, high, block in FORBIDDEN_RANGES:
                if low <= code <= high:
                    violations.append({
                        "rule": "forbidden-unicode",
                        "severity": "error",
                        "line": number, "column": column,
                        "detail": "U+%04X (%s) renders as '?' in the GitHub web UI"
                                  % (code, block),
                        "fix": "use ASCII: --> or -> for arrows, | for verticals, "
                               "+ - | for boxes, or a mermaid block",
                    })
                    break

        if in_fence:
            continue

        match = HEADING.match(line)
        if not match:
            continue
        level, title = len(match.group(1)), match.group(2)
        headings.append({"line": number, "level": level, "title": title,
                         "anchor": slugify(title)})

        for column, ch in enumerate(title, start=1):
            if _is_emoji(ch):
                violations.append({
                    "rule": "emoji-in-heading", "severity": "error",
                    "line": number, "column": column,
                    "detail": "emoji U+%04X in a heading" % ord(ch),
                    "fix": "headings must be plain ASCII; move the emoji to body text",
                })
                break
        if EMOJI_SHORTCODE.search(title):
            violations.append({
                "rule": "emoji-shortcode-in-heading", "severity": "error",
                "line": number,
                "detail": "emoji shortcode in a heading: " + title,
                "fix": "remove the shortcode; headings must be plain ASCII",
            })
        if "&" in title:
            violations.append({
                "rule": "ampersand-in-heading", "severity": "error",
                "line": number,
                "detail": "'&' in heading: " + title,
                "fix": "use 'and' — GitHub anchors for '&' headings are unreliable",
            })
        if any(ord(ch) > 127 for ch in title):
            non_ascii = [ch for ch in title if ord(ch) > 127]
            violations.append({
                "rule": "non-ascii-heading", "severity": "warning",
                "line": number,
                "detail": "non-ASCII characters in heading: " + "".join(sorted(set(non_ascii))),
                "fix": "prefer plain ASCII headings so anchors stay predictable",
            })

    anchors = {h["anchor"] for h in headings}
    seen = {}
    for h in headings:
        seen[h["anchor"]] = seen.get(h["anchor"], 0) + 1
    for anchor, count in sorted(seen.items()):
        if count > 1:
            violations.append({
                "rule": "duplicate-anchor", "severity": "warning",
                "detail": "%d headings produce the anchor '#%s'" % (count, anchor),
                "fix": "make the heading text unique; GitHub disambiguates with -1, -2 suffixes",
            })

    for number, line in enumerate(lines, start=1):
        for target in MD_LINK.findall(line):
            base = target.split("?")[0]
            if base and base not in anchors and not re.match(r".*-\d+$", base):
                violations.append({
                    "rule": "broken-toc-anchor", "severity": "error",
                    "line": number,
                    "detail": "link to '#%s' matches no heading" % base,
                    "fix": "anchors are lowercase-hyphenated slugs of the heading text",
                })

    missing_sections = []
    if require_sections:
        titles = " \n ".join(h["title"] for h in headings)
        for section in REQUIRED_SECTIONS:
            if section.lower() not in titles.lower():
                missing_sections.append(section)
        for section in missing_sections:
            violations.append({
                "rule": "missing-required-section", "severity": "error",
                "detail": "required section absent: " + section,
                "fix": "see reference/readme-generation.md for the required order",
            })

        top = [h["title"].lower() for h in headings[:4]]
        if headings and not any("the rundown" in t for t in top):
            violations.append({
                "rule": "section-order", "severity": "error",
                "detail": "The Rundown must be at the very top",
                "fix": "put The Rundown immediately after the project identity header",
            })

    errors = [v for v in violations if v["severity"] == "error"]
    return {
        "path": path_label,
        "status": "PASS" if not errors else "FAIL",
        "counts": {
            "errors": len(errors),
            "warnings": len(violations) - len(errors),
            "headings": len(headings),
        },
        "missing_required_sections": missing_sections,
        "violations": violations,
        "headings": headings,
    }
