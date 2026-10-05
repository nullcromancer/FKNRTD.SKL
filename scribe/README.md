# scribe

**Writes like a person, not a presentation template.**

Scribe is an always-on prose style skill for assistants and CLIs. It exists because technically correct writing can still read like it was assembled from a box of AI mannerisms: one-sentence paragraphs, fake dramatic pauses, em dashes everywhere, excessive headings, predictable contrast formulas, and jokes placed on their own line so nobody accidentally misses them.

Scribe fixes the presentation without weakening the content. It keeps paragraphs cohesive, varies sentence rhythm naturally, uses lists only when lists are useful, removes canned transitions, and keeps light sarcasm inside the prose instead of turning the page into a collection of punchlines. It also explicitly refuses to make writing "human" by inserting typos, fake anecdotes, or manufactured uncertainty.

The skill is intended to stay active for reader-facing prose while leaving code, commands, paths, identifiers, logs, structured data, exact quotations, and requested technical formats alone.

## Core rules

- Normal paragraphs should usually contain multiple related sentences.
- Merge needless single-sentence paragraphs before sending substantial prose.
- Do not use em dashes unless the user explicitly requests them.
- Do not substitute double hyphens for em dashes.
- Avoid repetitive AI formulas such as `It's not X. It's Y.` and `The result? X.`
- Keep dry humor and sarcasm inside normal prose instead of isolating every joke.
- Avoid excessive headings, bullets, bolding, and decorative formatting in article-style writing.
- Do not add typos or fake personal experiences to simulate humanity.
- Accuracy, requirements, clarity, and requested formats always outrank style.

Start with `SKILL.md`.

## Install

Run:

```bash
python install.py
```

The installer copies the `scribe` folder into the supported local skill directories it can find or create:

- `~/.claude/skills/scribe`
- `~/.agents/skills/scribe`
- `~/.cline/skills/scribe`
- `~/.copilot/skills/scribe`

Scribe is designed to be treated as an always-on writing rule by clients that support automatically loaded skills. Clients that require explicit skill invocation may need their own configuration to load it for every session.
