# Output profiles

odin only needs to understand the project once. After that, it can hand the same evidence to different people without making up a different version of reality for each one.

The default is still the forensic packet. Presentation outputs are optional and caller-driven.

## Output selection

Resolve the requested profile from the caller's wording. Do not ask a follow-up question if the intent is clear.

| Caller asks for | Profile | Output |
| --- | --- | --- |
| audit, findings, forensic packet, evidence packet | `packet` | `findings.zip` |
| GitHub README, repo README, document this repository | `readme` | `README.md` plus `logo.png` |
| interactive docs, documentation website, project site | `website` | runnable site directory plus `logo.png` |
| handoff, developer handoff, teach another team or CLI | `handoff` | `PROJECT_HANDOFF.md` |
| everything, all outputs, full documentation package | `all` | packet plus all presentation outputs |

If the caller does not name a presentation output, use `packet`. That preserves odin's original behavior.

Generated presentation artifacts belong under `ARTIFACT_ROOT/outputs/` by default. Do not casually spray generated files into the repository being analysed. If the caller explicitly asks odin to update the repository's own README, follow the repository-README rules in `reference/readme-generation.md` and keep the modification scoped to the requested documentation artifact.

## One evidence model, several renderers

The scan owns facts. Renderers own wording and layout.

```text
repository
   |
   v
odin analysis
   |
   v
normalized evidence
   |
   +--> findings.zip
   +--> README.md
   +--> PROJECT_HANDOFF.md
   +--> interactive documentation site
```

README, website, and handoff outputs generated from the same run must agree on project identity, component names, paths, versions, commands, test state, security findings, deployment facts, dates supported by evidence, and unfinished work.

If two outputs disagree, the renderer is wrong. Fix the renderer. Do not invent a compromise.

## Shared opening

The README and website both start with:

1. `reference/logo.png` from this skill, copied into the generated output as `logo.png`;
2. the project name;
3. a short, plain-language summary of what the project actually does;
4. **The Rundown**, which combines business context and technical context into one readable section.

The handoff is plain Markdown and does not need the visual theme, but it still begins with the project name and The Rundown.

## Voice

Human-facing documentation should sound like a good developer wrote it after actually reading the code.

Target voice: casual, technically exact, dry, mildly irreverent, hacker-ish, and occasionally funny. Think somebody who can explain the architecture, spot a bad abstraction, and make one joke about it without turning the README into open-mic night.

Rules:

- Use contractions when they sound natural.
- Prefer normal words over corporate sludge.
- A little gallows humor is fine. Keep it away from commands, security claims, versions, paths, and anything somebody will copy into a terminal.
- Do not use canned assistant phrases such as "this section will discuss", "seamlessly", "robust", "cutting-edge", "leverage", or "in today's fast-paced" unless the repository itself is being quoted.
- Do not narrate the act of writing documentation.
- Do not repeat the same point in three slightly different ways just to sound thorough.
- Avoid em dashes and en dashes in generated prose. Use a comma, colon, period, or parentheses instead. ASCII `--` inside real CLI flags is obviously fine.
- Do not force jokes. The technical material is the reason the document exists.
- If the evidence does not know, say so plainly. "Insufficient Evidence" is a perfectly respectable answer.
- Never let personality weaken a warning, soften a security finding, or blur the difference between observed and inferred behavior.

## GitHub README profile

The README is a project manual, not a landing-page postcard.

Use `reference/readme-generation.md` as the full contract. At minimum it should cover the project's purpose, The Rundown, architecture, components, stack, layout, setup, configuration, run/build/test commands, public surfaces, data and integrations, security, observability, deployment, troubleshooting, known gaps, contribution guidance, and Change Log.

GitHub controls the page CSS. Do not pretend otherwise. Carry the black-and-green nullcromancer feel through `logo.png`, terminal-style fenced blocks, concise status language, tables, green-compatible badges when appropriate, and ASCII or Mermaid diagrams. The content must still be readable in both GitHub light and dark modes.

## Interactive website profile

Build a real, runnable documentation site from the same evidence.

### Stack selection

Use this order:

1. the language or framework explicitly requested by the caller;
2. an existing web stack already present in the analysed project, when reusing it is sensible and does not require executing untrusted project code;
3. static HTML, CSS, and vanilla JavaScript as the deterministic fallback.

Do not ask the caller which stack they want if they already told you. Also do not decide that a C# request secretly means React because you got excited.

### Required experience

When evidence exists, include:

- `logo.png`, project name, summary, and The Rundown on the landing view;
- persistent navigation;
- client-side search or equivalent framework-native search;
- architecture and component views;
- repository layout and high-value paths;
- build, install, run, test, and validation commands;
- configuration reference;
- command, endpoint, route, API, or plugin surfaces as relevant;
- data-flow and integration documentation;
- security and observability sections;
- unfinished work and known limitations;
- onboarding path for a new developer;
- evidence references back to source paths;
- copyable commands and paths;
- responsive layout and accessible semantic markup.

### Visual direction

This is where the full nullcromancer treatment is allowed: black surfaces, green terminal accents, restrained glow, monospaced technical details, readable long-form text, and interactive panels that help navigation instead of decorating empty space.

Do not ship a screenshot pretending to be a site. Deliver source files that open or build.

### Validation

If the chosen stack can be validated without violating sandbox policy, run its static checks/build against the generated site. Never execute the analysed repository's code merely to prove the documentation site works.

Record what was validated and what was not.

## Developer handoff profile

Write `PROJECT_HANDOFF.md` for the person who gets the project next.

The handoff should answer, in practical terms:

- what the project is and why it exists;
- who or what consumes it;
- what works today;
- what is incomplete, risky, brittle, or weird;
- architecture and runtime flow;
- where a new developer should start reading;
- how to configure, build, test, run, debug, and deploy it;
- external systems and integrations;
- things that should not be casually changed;
- important conventions and architectural decisions;
- security-sensitive areas;
- operational procedures;
- known failure modes and technical debt;
- first-day, first-week, and first-change orientation;
- what another coding CLI should read before touching the code.

It may link to `findings.zip` for deeper evidence, but it has to stand on its own. Nobody should need to reverse-engineer the handoff document to understand the reverse-engineered project. That would be embarrassing.

Use `templates/project-handoff.md` as a starting skeleton, then replace every placeholder with evidence or an explicit `Insufficient Evidence` statement.

## All profile

`all` means all four deliverables. Do the analysis once, then render:

- `findings.zip`
- `outputs/README.md`
- `outputs/logo.png`
- `outputs/PROJECT_HANDOFF.md`
- `outputs/site/`

If the caller explicitly asked odin to update the repository README too, do that after the forensic integrity check and report the documentation mutation separately from the read-only analysis result.

## Completion summary

Report only artifacts actually produced. A requested output that is missing is a failure or partial result, not an opportunity for creative optimism.
