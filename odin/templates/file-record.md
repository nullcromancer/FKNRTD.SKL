# Template: `files/<repository-relative-path>.md`

`odin.py docstub` generates this shape with the Identity block already filled from
inventory evidence. Keep the headings; replace every `PENDING`.

A field that genuinely does not apply gets an explicit statement, not a blank:
"Not applicable: binary font asset with no source-level symbols."

---

```markdown
# src/core/parser.py

## Identity

- **Path:** `src/core/parser.py`
- **SHA-256:** `49d454e8…`
- **Size:** 4821 bytes, 168 lines
- **Filesystem type/mode:** regular-file, mode 0o644
- **File format:** Python source
- **Language(s):** Python (E5 extension `.py`; confirmed E8 by CPython 3.12 ast)
- **Content kind:** text, encoding utf-8, LF
- **Role:** first-party-source
- **Module:** `src-core`
- **Classification:** first-party (no vendor, generated or VCS-metadata signal)
- **Sensitive-content handling:** normal
- **Git state:** tracked=True

## Purpose / summary

One or two paragraphs: what this file is for, in the context of its module. Written
from the code, not from the docstring alone: and where the docstring and the code
disagree, say so.

## Key symbols and types

| Symbol | Kind | Visibility | Signature | Notes |
| --- | --- | --- | --- | --- |
| `Parser` | class | public |: | main entry type |
| `Parser.parse` | method | public | `(self, text: str) -> Ast` | raises `ParseError` |
| `_tokenize` | function | private | `(text: str) -> Iterator[Token]` | |

Backend: CPython `ast` (semantic). Types shown are declared annotations, not inferred.

## Imports, exports, dependencies

- Imports: `re` (stdlib), `src.core.tokens` (internal), `attrs>=23.1` (external, DECLARED)
- Exports / public API: `Parser`, `ParseError`
- Unresolved imports: none

## Callers, callees, references

- Called by: `src/cli/main.py:41`, `src/api/routes.py:88` (DERIVED)
- Calls: `src/core/tokens.py::tokenize` (DERIVED)
- Referenced by non-code artifacts: `docs/parsing.md`, `pyproject.toml` entry point

## Runtime and control-flow behavior

Entry points, lifecycle, error paths, concurrency, and what happens on failure.

## Data flow and I/O

Inputs and outputs, filesystem reads/writes, network, serialization boundaries,
trust boundaries the data crosses.

## Configuration and environment usage

Environment variables read, configuration keys consumed, feature flags, defaults.

## Security observations

Concrete observations with evidence, or "No security-relevant behavior observed in
static analysis; the file performs no I/O, execution, deserialization or credential
handling."

## Tests touching or referring to this file

`tests/test_parser.py` (12 tests, DECLARED by import), `tests/e2e/test_cli.py`
(indirect).

## Measured coverage

Not measured. *- or -* 87.4% line coverage, 71.0% branch (coverage.py 7.5.0,
OBSERVED, `tests/coverage/coverage.json`).

## TODO / unfinished work

- `UNFIN-000123` line 92, TODO(alice): handle retries, issue #123

## Related files and modules

`src/core/tokens.py`, `src/core/ast.py`, module `src-core`.

## Evidence class and confidence

Symbols and imports: DERIVED, High (native parser). Caller list: DERIVED, Medium
(static call graph; dynamic dispatch unresolved). Purpose: DERIVED + DOCUMENTED, High.

## Parse and tool errors

None.

## Limitations and unknowns

Dynamic `getattr` dispatch at line 140 could not be resolved statically; the set of
reachable handlers is unknown without execution.
```
