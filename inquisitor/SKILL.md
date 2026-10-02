---
name: inquisitor
description: >
  Interrogate the user with a structured questionnaire and keep their answers. Use when a
  project, design, migration or plan has many open decisions and the user asks to be
  grilled, quizzed, interviewed, or asked "all the questions that remain", or wants a
  decision sheet they can answer at their own pace. Produces ./inquisitor/inquisitor.html
  (questions, options, a recommended answer with reasons, free-text input, notes, defer)
  that autosaves to ./inquisitor/answers.md so no progress is lost, then reads answers.md
  back as the spec. Works for any project or topic.
metadata:
  version: "1.0.0"
---

# Inquisitor

Turn "what is still undecided?" into a page the user can answer, and a file you can read back.

Output, always relative to the **current working directory**:

```
./inquisitor/inquisitor.html   the questionnaire (self-contained, opens from disk, no network)
./inquisitor/questions.json    the spec it was built from (kept so it can be rebuilt)
./inquisitor/answers.md        written by the page as the user answers; the file you read back
```

## Procedure

1. **Ground the questions in the real project.** Read what exists (READMEs, AGENTS/CLAUDE.md,
   status notes, key sources) before asking anything. A question whose answer is in the repo is a
   failure. Quote what you found in the `why` of each question and in `context`.
2. **Find the real tensions.** Where the user's goal conflicts with their own stated rules,
   say so (`context` block with `"kind": "tension"`) and turn it into a `blocker` question.
3. **Write the spec** to `./inquisitor/questions.json` (format below). Typically 30 to 80
   questions in 6 to 12 sections. Group by decision area, not by chronology.
4. **Build**: `python <skill-dir>/scripts/build.py ./inquisitor/questions.json`
   (`<skill-dir>` is the folder holding this SKILL.md). It validates, then writes
   `./inquisitor/inquisitor.html`. Fix any validation errors it lists.
5. **Tell the user** to open `inquisitor/inquisitor.html` in Chrome or Edge, click **Connect
   folder**, pick the `inquisitor` folder once, and answer. Every answer rewrites `answers.md`
   within a second and is restored on reopening. Other browsers keep answers in the browser only
   and download `answers.md` on Finish. Do not claim the file is being written until the user
   confirms they connected the folder.
6. **When the user returns**: run `python <skill-dir>/scripts/build.py --status` for counts and
   open blockers, then read `./inquisitor/answers.md`. Rules for using it:
   - Answers are binding decisions. Own-answer text and notes override the option text.
   - `accepted in bulk` is a default the user did not consider individually: confirm before
     anything expensive or irreversible.
   - `DEFERRED` and `unanswered` are open. Never assume them. Ask again or say you are blocked.
   - Ignore the `INQUISITOR-STATE` comment at the end of the file.
7. **Rounds**: to ask follow-ups, edit `questions.json` (add or change questions, keep existing
   ids stable) and rebuild. Answers are keyed by question id and survive a rebuild. Never reuse
   an id for a different question.

## Spec format (`questions.json`)

```json
{
  "title": "Payments migration: open decisions",
  "subtitle": "One line on what this is for.",
  "contextTitle": "What I found",
  "context": [
    {"heading": "What is real", "items": ["fact with source"]},
    {"heading": "Where the goal fights your rules", "kind": "tension", "items": ["..."]}
  ],
  "contextNote": "Sources and what was not verified.",
  "sections": [{"id": "A", "title": "Scope: what is in", "blurb": "Why this section exists."}],
  "questions": [
    {
      "id": "A1", "section": "A", "priority": "blocker",
      "text": "Which provider is the system of record?",
      "why": "Grounding from the repo: `billing/` calls both today.",
      "multi": false,
      "options": [
        {"label": "Provider X", "detail": "Consequence of choosing it.", "recommended": true},
        {"label": "Provider Y", "detail": "..."}
      ],
      "recommendation": "Why the recommended option is the right one.",
      "freeText": "Placeholder for the own-answer box (required when there are no options)"
    }
  ]
}
```

Rules the validator enforces: unique ids matching `[A-Za-z0-9._-]`; every question names an
existing section; `priority` is `blocker`, `important` or `later` (default `important`); zero
options (free text, needs `freeText`) or at least two; at most one `recommended` option unless
`multi` is true; any recommended option needs a `recommendation` (the why). `**bold**` and
`` `code` `` work in text fields; other markup is escaped.

## Writing good questions

- Offer real alternatives with their consequences in `detail`. Mark **one** option recommended
  when you can defend it from evidence, and say why. Leave it unmarked when you cannot; do not
  invent a recommendation to fill the slot.
- Tag honestly. `blocker` means the design or next step cannot proceed without it.
- Use `multi` for "which of these apply", with a recommended subset.
- Use free-text questions (no options) for pain points, success scenes, trust limits and
  "what did I fail to ask".
- Ask the user for decisions only they can make. Do not ask for facts you can read.
- Do not pad. Fewer sharp questions beat many vague ones.

## Limits

- Browsers cannot silently write to an arbitrary path, so the user connects the folder once per
  browser profile. The folder handle is remembered; on a later visit a click may re-grant access.
- The page is a static file. It does not call any model or network.
- Rebuilding overwrites `inquisitor.html` and `questions.json` but never touches `answers.md`.
