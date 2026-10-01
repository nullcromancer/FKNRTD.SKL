"""Deterministic first-pass file format / language / role classification.

This module produces *evidence-bearing hints*, never final verdicts. Every
result carries the evidence rule that produced it so the agent can confirm,
override, or escalate to a real parser. Contradictory signals are preserved
as alternatives rather than discarded.

Evidence rules, strongest first (mirrors the odin protocol order):
  E1 repository metadata (.gitattributes linguist-* attributes)
  E2 standard / special filename
  E3 editor modeline
  E4 shebang / interpreter declaration
  E5 unambiguous extension
  E6 magic number / formal file header
  E7 structured-language root or header
  E10 deterministic content heuristic

E8 (native parser) and E9 (tree-sitter) are outside this module's scope and
are applied by the agent during the static-analysis phase.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# E6 magic numbers
# --------------------------------------------------------------------------

MAGIC = [
    (b"\x7fELF", "ELF executable/shared object", "application/x-elf"),
    (b"MZ", "DOS/PE executable", "application/vnd.microsoft.portable-executable"),
    (b"\xca\xfe\xba\xbe", "Java class or Mach-O fat binary", "application/java-vm"),
    (b"\xfe\xed\xfa\xce", "Mach-O binary (32-bit)", "application/x-mach-binary"),
    (b"\xfe\xed\xfa\xcf", "Mach-O binary (64-bit)", "application/x-mach-binary"),
    (b"PK\x03\x04", "ZIP container (zip/jar/whl/docx/xlsx/apk/...)", "application/zip"),
    (b"PK\x05\x06", "ZIP container (empty)", "application/zip"),
    (b"\x1f\x8b", "gzip stream", "application/gzip"),
    (b"BZh", "bzip2 stream", "application/x-bzip2"),
    (b"\xfd7zXZ\x00", "xz stream", "application/x-xz"),
    (b"\x28\xb5\x2f\xfd", "zstandard stream", "application/zstd"),
    (b"7z\xbc\xaf\x27\x1c", "7-Zip archive", "application/x-7z-compressed"),
    (b"Rar!\x1a\x07", "RAR archive", "application/vnd.rar"),
    (b"ustar", "tar archive (offset 257)", "application/x-tar"),
    (b"%PDF-", "PDF document", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "PNG image", "image/png"),
    (b"\xff\xd8\xff", "JPEG image", "image/jpeg"),
    (b"GIF87a", "GIF image", "image/gif"),
    (b"GIF89a", "GIF image", "image/gif"),
    (b"BM", "BMP image", "image/bmp"),
    (b"RIFF", "RIFF container (wav/avi/webp)", "application/x-riff"),
    (b"OggS", "Ogg container", "application/ogg"),
    (b"ID3", "MP3 with ID3 tag", "audio/mpeg"),
    (b"fLaC", "FLAC audio", "audio/flac"),
    (b"\x00asm", "WebAssembly module", "application/wasm"),
    (b"SQLite format 3\x00", "SQLite database", "application/vnd.sqlite3"),
    (b"\xed\xab\xee\xdb", "RPM package", "application/x-rpm"),
    (b"!<arch>", "ar archive (.a/.deb)", "application/x-archive"),
    (b"\x1a\x45\xdf\xa3", "Matroska/WebM container", "video/x-matroska"),
    (b"-----BEGIN ", "PEM-encoded key or certificate", "application/x-pem-file"),
    (b"\x30\x82", "DER-encoded ASN.1 (certificate/key)", "application/pkix-cert"),
    (b"\xef\xbb\xbf", "UTF-8 BOM text", "text/plain"),
    (b"\xff\xfe", "UTF-16LE BOM text", "text/plain"),
    (b"\xfe\xff", "UTF-16BE BOM text", "text/plain"),
    (b"\xd0\xcf\x11\xe0", "OLE compound file (legacy Office)", "application/x-ole-storage"),
]

# --------------------------------------------------------------------------
# E5 extension -> (language, format)
# --------------------------------------------------------------------------

EXT_LANG = {
    # systems / compiled
    "c": "C", "h": "C/C++ header", "i": "C preprocessed",
    "cc": "C++", "cpp": "C++", "cxx": "C++", "c++": "C++",
    "hh": "C++ header", "hpp": "C++ header", "hxx": "C++ header", "ipp": "C++ header",
    "m": "Objective-C", "mm": "Objective-C++",
    "rs": "Rust", "go": "Go", "zig": "Zig", "d": "D", "nim": "Nim",
    "swift": "Swift", "java": "Java", "kt": "Kotlin", "kts": "Kotlin script",
    "scala": "Scala", "sc": "Scala script", "groovy": "Groovy", "clj": "Clojure",
    "cljs": "ClojureScript", "cljc": "Clojure", "erl": "Erlang", "hrl": "Erlang header",
    "ex": "Elixir", "exs": "Elixir script", "hs": "Haskell", "lhs": "Literate Haskell",
    "ml": "OCaml", "mli": "OCaml interface", "fs": "F#", "fsi": "F# interface",
    "fsx": "F# script", "cs": "C#", "vb": "Visual Basic", "pas": "Pascal",
    "ada": "Ada", "adb": "Ada", "ads": "Ada", "f": "Fortran", "f90": "Fortran",
    "f95": "Fortran", "for": "Fortran", "cob": "COBOL", "cbl": "COBOL",
    "asm": "Assembly", "s": "Assembly", "S": "Assembly",
    "v": "Verilog/Coq", "sv": "SystemVerilog", "vhd": "VHDL", "vhdl": "VHDL",
    "cu": "CUDA", "cuh": "CUDA header", "cl": "OpenCL",
    "sol": "Solidity", "move": "Move", "cairo": "Cairo",
    "gleam": "Gleam", "odin": "odin", "roc": "Roc", "gr": "Grain",
    "sml": "Standard ML", "ml4": "OCaml Camlp4 syntax extension",
    "agda": "Agda", "idr": "Idris", "lean": "Lean",
    "wat": "WebAssembly text", "bal": "Ballerina", "vale": "Vale",
    "pony": "Pony", "chpl": "Chapel", "fut": "Futhark",
    "mojo": "Mojo", "bend": "Bend",
    # scripting / dynamic
    "py": "Python", "pyi": "Python stub", "pyw": "Python", "pyx": "Cython",
    "pxd": "Cython", "ipynb": "Jupyter notebook",
    "rb": "Ruby", "rake": "Ruby", "gemspec": "Ruby",
    "pl": "Perl", "pm": "Perl module", "t": "Perl test",
    "php": "PHP", "phtml": "PHP", "lua": "Lua", "tcl": "Tcl",
    "r": "R", "rmd": "R Markdown", "jl": "Julia",
    "dart": "Dart", "hx": "Haxe", "cr": "Crystal", "rkt": "Racket",
    "scm": "Scheme", "ss": "Scheme", "el": "Emacs Lisp", "lisp": "Common Lisp",
    "ps1": "PowerShell", "psm1": "PowerShell module", "psd1": "PowerShell manifest",
    "sh": "Shell", "bash": "Bash", "zsh": "Zsh", "fish": "Fish", "ksh": "Ksh",
    "bat": "Batch", "cmd": "Batch", "awk": "AWK", "sed": "sed script",
    "vim": "Vim script", "nu": "Nushell",
    "janet": "Janet", "fnl": "Fennel",
    # web
    "js": "JavaScript", "mjs": "JavaScript (ESM)", "cjs": "JavaScript (CJS)",
    "jsx": "JavaScript JSX", "ts": "TypeScript", "tsx": "TypeScript TSX",
    "mts": "TypeScript (ESM)", "cts": "TypeScript (CJS)",
    "vue": "Vue SFC", "svelte": "Svelte", "astro": "Astro",
    "html": "HTML", "htm": "HTML", "xhtml": "XHTML",
    "css": "CSS", "scss": "SCSS", "sass": "Sass", "less": "Less", "styl": "Stylus",
    "coffee": "CoffeeScript", "elm": "Elm", "res": "ReScript", "re": "Reason",
    # data / config / markup
    "json": "JSON", "json5": "JSON5", "jsonc": "JSON with comments",
    "jsonl": "JSON Lines", "ndjson": "JSON Lines",
    "yaml": "YAML", "yml": "YAML", "toml": "TOML", "ini": "INI", "cfg": "INI",
    "conf": "Configuration", "properties": "Java properties",
    "xml": "XML", "xsd": "XML Schema", "xsl": "XSLT", "xslt": "XSLT",
    "dtd": "DTD", "plist": "Property list",
    "csv": "CSV", "tsv": "TSV", "parquet": "Parquet", "avro": "Avro",
    "proto": "Protocol Buffers", "thrift": "Thrift", "fbs": "FlatBuffers",
    "graphql": "GraphQL", "gql": "GraphQL", "capnp": "Cap'n Proto",
    "md": "Markdown", "markdown": "Markdown", "mdx": "MDX",
    "rst": "reStructuredText", "adoc": "AsciiDoc", "asciidoc": "AsciiDoc",
    "org": "Org mode", "tex": "LaTeX", "bib": "BibTeX", "txt": "Plain text",
    "sql": "SQL", "psql": "SQL", "ddl": "SQL", "prisma": "Prisma schema",
    "hcl": "HCL", "tf": "Terraform", "tfvars": "Terraform variables",
    "bicep": "Bicep", "nix": "Nix", "dhall": "Dhall", "cue": "CUE",
    "jsonnet": "Jsonnet", "libsonnet": "Jsonnet library",
    "mmd": "Mermaid", "mermaid": "Mermaid", "dot": "Graphviz DOT", "puml": "PlantUML",
    "env": "Environment file", "editorconfig": "EditorConfig",
    # build
    "mk": "Makefile", "make": "Makefile", "cmake": "CMake",
    "gradle": "Gradle", "bzl": "Starlark", "bazel": "Starlark", "star": "Starlark",
    "csproj": "MSBuild project", "fsproj": "MSBuild project",
    "vbproj": "MSBuild project", "vcxproj": "MSBuild project",
    "sln": "Visual Studio solution", "props": "MSBuild props",
    "targets": "MSBuild targets", "nuspec": "NuGet spec",
    "podspec": "CocoaPods spec", "pbxproj": "Xcode project",
    "sbt": "sbt build", "cabal": "Cabal", "opam": "OPAM",
    "spec": "RPM spec",
    # templates
    "j2": "Jinja2 template", "jinja": "Jinja2 template", "jinja2": "Jinja2 template",
    "tmpl": "Template", "tpl": "Template", "mustache": "Mustache",
    "hbs": "Handlebars", "ejs": "EJS", "erb": "ERB", "haml": "Haml",
    "slim": "Slim", "pug": "Pug", "jade": "Pug", "liquid": "Liquid",
    "twig": "Twig", "razor": "Razor", "cshtml": "Razor", "vbhtml": "Razor",
    "blade": "Blade", "njk": "Nunjucks",
    # assets / binary
    "png": "PNG image", "jpg": "JPEG image", "jpeg": "JPEG image",
    "gif": "GIF image", "webp": "WebP image", "bmp": "BMP image",
    "ico": "Icon", "svg": "SVG image", "avif": "AVIF image", "heic": "HEIC image",
    "tiff": "TIFF image", "tif": "TIFF image", "psd": "Photoshop document",
    "mp3": "MP3 audio", "wav": "WAV audio", "flac": "FLAC audio",
    "ogg": "Ogg audio", "m4a": "M4A audio",
    "mp4": "MP4 video", "webm": "WebM video", "mov": "QuickTime video",
    "avi": "AVI video", "mkv": "Matroska video",
    "ttf": "TrueType font", "otf": "OpenType font", "woff": "WOFF font",
    "woff2": "WOFF2 font", "eot": "EOT font",
    "pdf": "PDF document", "docx": "Word document", "xlsx": "Excel workbook",
    "pptx": "PowerPoint presentation", "odt": "OpenDocument text",
    "zip": "ZIP archive", "tar": "TAR archive", "gz": "gzip archive",
    "tgz": "gzip TAR archive", "bz2": "bzip2 archive", "xz": "xz archive",
    "zst": "zstd archive", "7z": "7-Zip archive", "rar": "RAR archive",
    "jar": "Java archive", "war": "Web archive", "whl": "Python wheel",
    "egg": "Python egg", "gem": "Ruby gem", "nupkg": "NuGet package",
    "deb": "Debian package", "rpm": "RPM package", "apk": "Android package",
    "dll": "Windows DLL", "so": "Shared object", "dylib": "Mach-O dylib",
    "exe": "Windows executable", "a": "Static library", "lib": "Static library",
    "o": "Object file", "obj": "Object file", "pyc": "Python bytecode",
    "pyd": "Python extension module", "class": "Java class",
    "wasm": "WebAssembly module", "db": "Database file",
    "sqlite": "SQLite database", "sqlite3": "SQLite database",
    "bin": "Binary blob", "dat": "Data file", "pkl": "Python pickle",
    "pickle": "Python pickle", "npy": "NumPy array", "npz": "NumPy archive",
    "h5": "HDF5", "hdf5": "HDF5", "onnx": "ONNX model",
    "pt": "PyTorch checkpoint", "pth": "PyTorch checkpoint",
    "safetensors": "Safetensors model", "ckpt": "Model checkpoint",
    "pem": "PEM key/certificate", "crt": "Certificate", "cer": "Certificate",
    "key": "Private key material", "p12": "PKCS#12 keystore",
    "pfx": "PKCS#12 keystore", "jks": "Java keystore", "keystore": "Java keystore",
    "asc": "PGP armored data", "gpg": "GPG data", "sig": "Signature",
    "lock": "Lockfile", "log": "Log file", "map": "Source map",
    "patch": "Patch", "diff": "Diff", "snap": "Test snapshot",
}

# --------------------------------------------------------------------------
# E2 exact / special filenames -> (label, role)
# --------------------------------------------------------------------------

SPECIAL_NAMES = {
    # build systems
    "makefile": ("Makefile", "build"),
    "gnumakefile": ("Makefile", "build"),
    "cmakelists.txt": ("CMake", "build"),
    "meson.build": ("Meson", "build"),
    "configure": ("Autotools configure script", "build"),
    "configure.ac": ("Autoconf", "build"),
    "makefile.am": ("Automake", "build"),
    "build.gradle": ("Gradle build", "build"),
    "build.gradle.kts": ("Gradle build (Kotlin)", "build"),
    "settings.gradle": ("Gradle settings", "build"),
    "settings.gradle.kts": ("Gradle settings (Kotlin)", "build"),
    "gradle.properties": ("Gradle properties", "build"),
    "gradlew": ("Gradle wrapper", "build"),
    "gradlew.bat": ("Gradle wrapper", "build"),
    "mvnw": ("Maven wrapper", "build"),
    "mvnw.cmd": ("Maven wrapper", "build"),
    "pom.xml": ("Maven POM", "package-manifest"),
    "build.xml": ("Ant build", "build"),
    "build": ("BUILD (Bazel/Buck)", "build"),
    "build.bazel": ("Bazel BUILD", "build"),
    "workspace": ("Bazel WORKSPACE", "build"),
    "workspace.bazel": ("Bazel WORKSPACE", "build"),
    "module.bazel": ("Bazel module", "build"),
    "buck": ("Buck build", "build"),
    "pants.toml": ("Pants build", "build"),
    "justfile": ("Justfile", "build"),
    "taskfile.yml": ("Taskfile", "build"),
    "taskfile.yaml": ("Taskfile", "build"),
    "rakefile": ("Rakefile", "build"),
    "dune": ("Dune build", "build"),
    "dune-project": ("Dune project", "build"),
    "wscript": ("Waf build", "build"),
    "sconstruct": ("SCons build", "build"),
    "premake5.lua": ("Premake build", "build"),
    "meson_options.txt": ("Meson options", "build"),
    # manifests
    "package.json": ("npm manifest", "package-manifest"),
    "bower.json": ("Bower manifest", "package-manifest"),
    "deno.json": ("Deno manifest", "package-manifest"),
    "deno.jsonc": ("Deno manifest", "package-manifest"),
    "jsr.json": ("JSR manifest", "package-manifest"),
    "pyproject.toml": ("Python project manifest", "package-manifest"),
    "setup.py": ("setuptools script", "package-manifest"),
    "setup.cfg": ("setuptools config", "package-manifest"),
    "requirements.txt": ("pip requirements", "package-manifest"),
    "requirements-dev.txt": ("pip requirements (dev)", "package-manifest"),
    "constraints.txt": ("pip constraints", "package-manifest"),
    "pipfile": ("Pipenv manifest", "package-manifest"),
    "environment.yml": ("Conda environment", "package-manifest"),
    "environment.yaml": ("Conda environment", "package-manifest"),
    "cargo.toml": ("Cargo manifest", "package-manifest"),
    "go.mod": ("Go module", "package-manifest"),
    "go.work": ("Go workspace", "package-manifest"),
    "gemfile": ("Bundler manifest", "package-manifest"),
    "composer.json": ("Composer manifest", "package-manifest"),
    "mix.exs": ("Mix manifest", "package-manifest"),
    "rebar.config": ("Rebar manifest", "package-manifest"),
    "pubspec.yaml": ("Dart/Flutter manifest", "package-manifest"),
    "package.swift": ("Swift package manifest", "package-manifest"),
    "cpanfile": ("Perl CPAN manifest", "package-manifest"),
    "dub.json": ("DUB manifest", "package-manifest"),
    "nimble": ("Nimble manifest", "package-manifest"),
    "conanfile.txt": ("Conan manifest", "package-manifest"),
    "conanfile.py": ("Conan manifest", "package-manifest"),
    "vcpkg.json": ("vcpkg manifest", "package-manifest"),
    "shard.yml": ("Crystal shard manifest", "package-manifest"),
    "descriptionrmd": ("R package description", "package-manifest"),
    "description": ("R package DESCRIPTION", "package-manifest"),
    # lockfiles
    "package-lock.json": ("npm lockfile", "lockfile"),
    "npm-shrinkwrap.json": ("npm shrinkwrap", "lockfile"),
    "yarn.lock": ("Yarn lockfile", "lockfile"),
    "pnpm-lock.yaml": ("pnpm lockfile", "lockfile"),
    "bun.lockb": ("Bun lockfile", "lockfile"),
    "bun.lock": ("Bun lockfile", "lockfile"),
    "deno.lock": ("Deno lockfile", "lockfile"),
    "poetry.lock": ("Poetry lockfile", "lockfile"),
    "pdm.lock": ("PDM lockfile", "lockfile"),
    "uv.lock": ("uv lockfile", "lockfile"),
    "pipfile.lock": ("Pipenv lockfile", "lockfile"),
    "cargo.lock": ("Cargo lockfile", "lockfile"),
    "go.sum": ("Go checksum database", "lockfile"),
    "gemfile.lock": ("Bundler lockfile", "lockfile"),
    "composer.lock": ("Composer lockfile", "lockfile"),
    "mix.lock": ("Mix lockfile", "lockfile"),
    "pubspec.lock": ("Dart/Flutter lockfile", "lockfile"),
    "packages.lock.json": ("NuGet lockfile", "lockfile"),
    "package.resolved": ("Swift package resolution", "lockfile"),
    "gradle.lockfile": ("Gradle lockfile", "lockfile"),
    "flake.lock": ("Nix flake lockfile", "lockfile"),
    "conan.lock": ("Conan lockfile", "lockfile"),
    "renv.lock": ("renv lockfile", "lockfile"),
    # containers / deploy
    "dockerfile": ("Dockerfile", "build"),
    "containerfile": ("Containerfile", "build"),
    "docker-compose.yml": ("Compose file", "deployment"),
    "docker-compose.yaml": ("Compose file", "deployment"),
    "compose.yml": ("Compose file", "deployment"),
    "compose.yaml": ("Compose file", "deployment"),
    ".dockerignore": ("Docker ignore", "build"),
    "procfile": ("Procfile", "deployment"),
    "vercel.json": ("Vercel config", "deployment"),
    "netlify.toml": ("Netlify config", "deployment"),
    "fly.toml": ("Fly.io config", "deployment"),
    "app.yaml": ("App Engine config", "deployment"),
    "serverless.yml": ("Serverless framework config", "deployment"),
    "template.yaml": ("SAM/CloudFormation template", "deployment"),
    "chart.yaml": ("Helm chart", "deployment"),
    "values.yaml": ("Helm values", "deployment"),
    "kustomization.yaml": ("Kustomize config", "deployment"),
    "skaffold.yaml": ("Skaffold config", "deployment"),
    # CI
    ".travis.yml": ("Travis CI config", "ci"),
    ".gitlab-ci.yml": ("GitLab CI config", "ci"),
    "azure-pipelines.yml": ("Azure Pipelines config", "ci"),
    "jenkinsfile": ("Jenkins pipeline", "ci"),
    "cloudbuild.yaml": ("Cloud Build config", "ci"),
    "buildspec.yml": ("CodeBuild spec", "ci"),
    ".drone.yml": ("Drone CI config", "ci"),
    "appveyor.yml": ("AppVeyor config", "ci"),
    ".pre-commit-config.yaml": ("pre-commit config", "ci"),
    # docs / meta
    "readme": ("README", "documentation"),
    "readme.md": ("README", "documentation"),
    "readme.rst": ("README", "documentation"),
    "readme.txt": ("README", "documentation"),
    "changelog.md": ("Changelog", "documentation"),
    "changelog": ("Changelog", "documentation"),
    "contributing.md": ("Contributing guide", "documentation"),
    "code_of_conduct.md": ("Code of conduct", "documentation"),
    "security.md": ("Security policy", "documentation"),
    "license": ("License", "documentation"),
    "license.md": ("License", "documentation"),
    "license.txt": ("License", "documentation"),
    "copying": ("License", "documentation"),
    "notice": ("Notice", "documentation"),
    "authors": ("Authors", "documentation"),
    "codeowners": ("Code owners", "configuration"),
    "agents.md": ("Agent instructions", "documentation"),
    "claude.md": ("Agent instructions", "documentation"),
    # VCS / tooling config
    ".gitignore": ("Git ignore", "vcs-metadata"),
    ".gitattributes": ("Git attributes", "vcs-metadata"),
    ".gitmodules": ("Git submodules", "vcs-metadata"),
    ".gitkeep": ("Git placeholder", "vcs-metadata"),
    ".editorconfig": ("EditorConfig", "configuration"),
    ".nvmrc": ("Node version pin", "configuration"),
    ".node-version": ("Node version pin", "configuration"),
    ".python-version": ("Python version pin", "configuration"),
    ".ruby-version": ("Ruby version pin", "configuration"),
    ".tool-versions": ("asdf/mise tool versions", "configuration"),
    ".nvmrc.json": ("Node version pin", "configuration"),
    "rust-toolchain": ("Rust toolchain pin", "configuration"),
    "rust-toolchain.toml": ("Rust toolchain pin", "configuration"),
    "global.json": (".NET SDK pin", "configuration"),
    ".npmrc": ("npm config", "configuration"),
    ".yarnrc.yml": ("Yarn config", "configuration"),
    "tsconfig.json": ("TypeScript config", "configuration"),
    "jsconfig.json": ("JavaScript project config", "configuration"),
    ".eslintrc": ("ESLint config", "configuration"),
    ".eslintrc.json": ("ESLint config", "configuration"),
    "eslint.config.js": ("ESLint config", "configuration"),
    ".prettierrc": ("Prettier config", "configuration"),
    "tox.ini": ("tox config", "configuration"),
    "noxfile.py": ("nox config", "configuration"),
    "pytest.ini": ("pytest config", "configuration"),
    "conftest.py": ("pytest fixtures", "test"),
    ".env": ("Environment file", "secret-candidate"),
    ".env.local": ("Environment file", "secret-candidate"),
    ".env.example": ("Environment template", "configuration"),
    ".env.sample": ("Environment template", "configuration"),
    ".env.template": ("Environment template", "configuration"),
    ".npmignore": ("npm ignore", "configuration"),
    "devcontainer.json": ("Dev container config", "configuration"),
    "flake.nix": ("Nix flake", "build"),
    "shell.nix": ("Nix shell", "build"),
    "default.nix": ("Nix derivation", "build"),
}

# --------------------------------------------------------------------------
# role heuristics by path segment
# --------------------------------------------------------------------------

VENDOR_DIRS = {
    "node_modules", "vendor", "vendored", "third_party", "thirdparty", "3rdparty",
    "external", "externals", "bundled", "deps", "Godeps", "packages",
    "site-packages", "dist-packages", "bower_components", "jspm_packages",
    ".venv", "venv", "env", "virtualenv", ".virtualenv", "eggs", ".eggs",
    "Pods", "Carthage", ".cargo", ".gradle", ".m2", ".nuget", ".bundle",
}

BUILD_ARTIFACT_DIRS = {
    "dist", "build", "out", "output", "target", "bin", "obj", "_build",
    "cmake-build-debug", "cmake-build-release", "Debug", "Release",
    ".next", ".nuxt", ".svelte-kit", ".output", ".parcel-cache", ".turbo",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    ".nox", ".gradle", ".idea", ".vs", "coverage", "htmlcov", ".nyc_output",
    ".terraform", ".serverless", ".cache", "tmp", "temp", ".sass-cache",
}

TEST_DIR_NAMES = {
    "test", "tests", "spec", "specs", "__tests__", "__test__", "testing",
    "e2e", "integration-tests", "unit-tests", "acceptance", "features",
    "fixtures", "testdata", "test-data", "__mocks__", "mocks", "cypress",
}

DOC_DIR_NAMES = {"doc", "docs", "documentation", "manual", "guide", "guides",
                 "handbook", "wiki", "adr", "rfcs", "man"}

BENCH_DIR_NAMES = {"bench", "benches", "benchmark", "benchmarks", "perf"}

EXAMPLE_DIR_NAMES = {"example", "examples", "sample", "samples", "demo", "demos",
                     "playground", "cookbook", "recipes", "tutorial", "tutorials"}

IAC_DIR_NAMES = {"terraform", "tofu", "pulumi", "ansible", "helm", "charts",
                 "k8s", "kubernetes", "manifests", "deploy", "deployment",
                 "infra", "infrastructure", "cloudformation"}

CI_DIR_NAMES = {".github", ".gitlab", ".circleci", ".buildkite", ".woodpecker",
                ".azure", ".teamcity", ".jenkins"}

MIGRATION_DIR_NAMES = {"migrations", "migrate", "schema", "schemas", "alembic",
                       "liquibase", "flyway", "db"}

ASSET_DIR_NAMES = {"assets", "static", "public", "images", "img", "media",
                   "fonts", "icons", "resources", "res"}

TEST_FILE_PATTERNS = [
    re.compile(r"(^|[._-])test[._-]", re.I),
    re.compile(r"[._-]test(s)?\.[A-Za-z0-9]+$", re.I),
    re.compile(r"[._-]spec\.[A-Za-z0-9]+$", re.I),
    re.compile(r"^test_.*\.(py|rb)$", re.I),
    re.compile(r".*_test\.(go|py|rb|rs|cc|cpp|java|ts|js)$", re.I),
    re.compile(r".*Test(s)?\.(java|kt|cs|scala)$"),
    re.compile(r".*\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs)$", re.I),
]

SENSITIVE_NAME_PATTERNS = [
    re.compile(r"(^|[._-])(secret|secrets|credential|credentials|password|passwd)s?($|[._-])", re.I),
    re.compile(r"(^|[._-])(token|apikey|api_key|private[._-]?key|id_rsa|id_ed25519)($|[._-])", re.I),
    re.compile(r"\.(pem|key|p12|pfx|jks|keystore|kdbx|ppk)$", re.I),
    re.compile(r"(^|/)\.env(\.(?!example|sample|template|dist|schema).*)?$", re.I),
    re.compile(r"(^|/)\.(aws|ssh|gnupg|docker|kube|npmrc|netrc|pypirc)$", re.I),
    re.compile(r"(^|[._-])(service[._-]?account|serviceaccount)($|[._-])", re.I),
]

GENERATED_CONTENT_MARKERS = [
    "@generated",
    "Code generated by",
    "DO NOT EDIT",
    "do not edit this file",
    "This file was automatically generated",
    "This file is auto-generated",
    "autogenerated",
    "auto-generated",
    "Generated by the protocol buffer compiler",
    "Generated by Django",
    "machine generated",
    "@nolint",
]

GENERATED_PATH_PATTERNS = [
    re.compile(r"\.pb\.(go|py|cc|h|js|ts|rb|java|cs)$"),
    re.compile(r"_pb2(_grpc)?\.pyi?$"),
    re.compile(r"\.generated\.[A-Za-z0-9]+$"),
    re.compile(r"(^|/)generated(/|$)"),
    re.compile(r"(^|/)gen(/|$)"),
    re.compile(r"\.g\.(dart|cs|ts)$"),
    re.compile(r"\.designer\.cs$", re.I),
    re.compile(r"\.min\.(js|css)$"),
    re.compile(r"\.d\.ts$"),
    re.compile(r"\.map$"),
    re.compile(r"(^|/)__generated__(/|$)"),
]

MODELINE = re.compile(
    r"(?:-\*-.*?mode:\s*([A-Za-z0-9_+-]+).*?-\*-)|(?:\b(?:vi|vim|ex):.*?\b(?:ft|filetype|syntax)=([A-Za-z0-9_+-]+))"
)

SHEBANG_LANG = {
    "python": "Python", "python2": "Python", "python3": "Python",
    "node": "JavaScript", "deno": "TypeScript/JavaScript", "bun": "TypeScript/JavaScript",
    "sh": "Shell", "bash": "Bash", "zsh": "Zsh", "dash": "Shell", "ksh": "Ksh",
    "fish": "Fish", "perl": "Perl", "ruby": "Ruby", "php": "PHP", "lua": "Lua",
    "Rscript": "R", "julia": "Julia", "awk": "AWK", "gawk": "AWK",
    "pwsh": "PowerShell", "powershell": "PowerShell", "tclsh": "Tcl",
    "groovy": "Groovy", "scala": "Scala", "kotlin": "Kotlin", "swift": "Swift",
    "elixir": "Elixir", "escript": "Erlang", "osascript": "AppleScript",
    "make": "Makefile", "env": None,
}


NON_SOURCE_LABELS = {
    "Plain text", "Markdown", "MDX", "reStructuredText", "AsciiDoc", "Org mode",
    "LaTeX", "BibTeX", "CSV", "TSV", "JSON", "JSON5", "JSON Lines", "YAML",
    "TOML", "INI", "XML", "Configuration", "Java properties", "Property list",
    "Lockfile", "Log file", "Patch", "Diff", "Test snapshot", "Source map",
    "Environment file", "EditorConfig", "Binary blob", "Data file",
    "Plain text (unclassified)", "Binary (unclassified)", "Empty file",
}


def is_source_language(label) -> bool:
    """True when a classification label denotes executable/compilable source."""
    if not label:
        return False
    if label in NON_SOURCE_LABELS:
        return False
    if label in EXT_LANG.values():
        lowered = label.lower()
        for marker in ("image", "audio", "video", "font", "archive", "package",
                       "document", "workbook", "presentation", "database",
                       "certificate", "key", "checkpoint", "model", "bytecode"):
            if marker in lowered:
                return False
        return True
    return False


def detect_magic(head: bytes):
    """Return (format_label, mime, matched_prefix_hex) for E6, or None."""
    for prefix, label, mime in MAGIC:
        if prefix == b"ustar":
            if len(head) > 262 and head[257:262] == b"ustar":
                return (label, mime, prefix.hex())
            continue
        if head.startswith(prefix):
            return (label, mime, prefix.hex())
    return None


def detect_shebang(head: bytes):
    """Return (interpreter, language) for E4, or None."""
    if not head.startswith(b"#!"):
        return None
    line = head.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    parts = line[2:].strip().split()
    if not parts:
        return None
    interp = parts[0].rsplit("/", 1)[-1]
    if interp == "env" and len(parts) > 1:
        for token in parts[1:]:
            if not token.startswith("-"):
                interp = token.rsplit("/", 1)[-1]
                break
    base = re.sub(r"[0-9.]+$", "", interp) or interp
    lang = SHEBANG_LANG.get(interp) or SHEBANG_LANG.get(base)
    return (line, lang)


def detect_modeline(text_head: str):
    """Return declared mode/filetype for E3, or None."""
    match = MODELINE.search(text_head)
    if not match:
        return None
    return match.group(1) or match.group(2)


def detect_structured_root(text_head: str):
    """Return a structured-language root/header label for E7, or None."""
    stripped = text_head.lstrip()
    low = stripped[:200].lower()
    if low.startswith("<?xml"):
        return "XML declaration"
    if low.startswith("<!doctype html"):
        return "HTML doctype"
    if low.startswith("<!doctype"):
        return "SGML/XML doctype"
    if low.startswith("<svg"):
        return "SVG root element"
    if low.startswith("<html"):
        return "HTML root element"
    if low.startswith("---\n") or low.startswith("---\r\n"):
        return "YAML document start or front matter"
    if stripped[:1] in "{[" and stripped[-0:] == "":
        return "JSON-like opening token"
    if low.startswith("%pdf-"):
        return "PDF header"
    if low.startswith("diff --git") or low.startswith("--- a/"):
        return "unified diff header"
    if low.startswith("-----begin "):
        return "PEM header"
    return None


def classify_extension(name: str):
    """Return (extension, language_or_format) for E5."""
    lower = name.lower()
    for compound in ("tar.gz", "tar.bz2", "tar.xz", "tar.zst",
                     "d.ts", "test.ts", "spec.ts", "min.js", "min.css"):
        if lower.endswith("." + compound):
            ext = compound
            return (ext, EXT_LANG.get(compound.split(".")[-1]))
    if "." not in lower.lstrip("."):
        return ("", None)
    ext = lower.rsplit(".", 1)[-1]
    return (ext, EXT_LANG.get(ext))


def path_segments(rel_path: str):
    return rel_path.split("/")[:-1]


def role_hints(rel_path: str, name: str, ext: str):
    """Return a list of (role, evidence) pairs, strongest first."""
    hints = []
    segs = path_segments(rel_path)
    segs_lower = [s.lower() for s in segs]
    lower_name = name.lower()

    if rel_path == ".git" or rel_path.startswith(".git/"):
        hints.append(("vcs-metadata", "path is inside the .git directory"))
    if any(s in (".svn", ".hg", ".bzr", "CVS") for s in segs) or name in (".svn", ".hg"):
        hints.append(("vcs-metadata", "path is inside a non-Git VCS directory"))

    special = SPECIAL_NAMES.get(lower_name)
    if special:
        hints.append((special[1], "special filename: " + special[0]))

    for seg in segs:
        if seg in VENDOR_DIRS:
            hints.append(("vendored", "path segment '" + seg + "' is a conventional dependency directory"))
            break
    for seg in segs:
        if seg in BUILD_ARTIFACT_DIRS:
            hints.append(("cache-or-build-artifact", "path segment '" + seg + "' is a conventional build/cache directory"))
            break
    for seg in segs_lower:
        if seg in CI_DIR_NAMES:
            hints.append(("ci", "path segment '" + seg + "' is a CI configuration directory"))
            break
    for seg in segs_lower:
        if seg in TEST_DIR_NAMES:
            hints.append(("test", "path segment '" + seg + "' is a conventional test directory"))
            break
    for pattern in TEST_FILE_PATTERNS:
        if pattern.search(name):
            hints.append(("test", "filename matches test naming convention"))
            break
    for seg in segs_lower:
        if seg in BENCH_DIR_NAMES:
            hints.append(("benchmark", "path segment '" + seg + "' is a benchmark directory"))
            break
    for seg in segs_lower:
        if seg in EXAMPLE_DIR_NAMES:
            hints.append(("example", "path segment '" + seg + "' is an example directory"))
            break
    for seg in segs_lower:
        if seg in DOC_DIR_NAMES:
            hints.append(("documentation", "path segment '" + seg + "' is a documentation directory"))
            break
    for seg in segs_lower:
        if seg in IAC_DIR_NAMES:
            hints.append(("deployment-iac", "path segment '" + seg + "' is an infrastructure directory"))
            break
    for seg in segs_lower:
        if seg in MIGRATION_DIR_NAMES:
            hints.append(("database-schema-migration", "path segment '" + seg + "' is a schema/migration directory"))
            break
    for seg in segs_lower:
        if seg in ASSET_DIR_NAMES:
            hints.append(("asset-media", "path segment '" + seg + "' is an asset directory"))
            break

    if ext in ("tf", "tfvars", "bicep", "hcl"):
        hints.append(("deployment-iac", "infrastructure-as-code extension"))
    if ext in ("md", "markdown", "rst", "adoc", "asciidoc", "org", "mdx", "tex"):
        hints.append(("documentation", "documentation markup extension"))
    if ext in ("sql", "ddl", "prisma"):
        hints.append(("database-schema-migration", "schema/query extension"))
    if ext in ("png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "mp3", "mp4",
               "wav", "ttf", "otf", "woff", "woff2", "webm", "mov", "avif"):
        hints.append(("asset-media", "media/font extension"))
    if ext in ("csv", "tsv", "parquet", "avro", "jsonl", "ndjson", "npy", "npz", "h5", "hdf5"):
        hints.append(("dataset", "tabular/array data extension"))
    if ext in ("so", "dll", "dylib", "a", "lib", "o", "obj", "exe", "class",
               "pyc", "jar", "war", "wasm"):
        hints.append(("binary-library-executable", "compiled artifact extension"))

    for pattern in SENSITIVE_NAME_PATTERNS:
        if pattern.search(rel_path):
            hints.append(("secret-candidate", "path matches a sensitive-name pattern"))
            break

    if not hints:
        hints.append(("unknown", "no filename, path or extension rule matched"))
    return hints


def origin_hints(rel_path: str, name: str, text_head: str):
    """Return (origin, evidence) for first-party / generated / vendored."""
    segs = rel_path.split("/")[:-1]
    if rel_path == ".git" or rel_path.startswith(".git/"):
        return ("vcs-metadata", "inside the .git directory")
    for seg in segs:
        if seg in VENDOR_DIRS:
            return ("vendored", "inside conventional dependency directory '" + seg + "'")
    for pattern in GENERATED_PATH_PATTERNS:
        if pattern.search(rel_path):
            return ("generated", "path matches generated-artifact pattern " + pattern.pattern)
    if text_head:
        head = text_head[:4096]
        for marker in GENERATED_CONTENT_MARKERS:
            if marker.lower() in head.lower():
                return ("generated", "content declares generation marker: " + marker)
    for seg in segs:
        if seg in BUILD_ARTIFACT_DIRS:
            return ("generated", "inside conventional build/cache directory '" + seg + "'")
    return ("first-party", "no vendor, generated or VCS-metadata signal matched")
