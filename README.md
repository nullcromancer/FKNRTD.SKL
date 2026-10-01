# inquisitor

A skill that interrogates the user about a project and keeps the answers.

The assistant reads the project, writes a question spec, and builds a self-contained page:

```
./inquisitor/inquisitor.html   questions, options, a recommended answer with reasons, free text, notes, defer
./inquisitor/answers.md        written by the page after every answer; handed back to the assistant
./inquisitor/questions.json    the spec (rebuildable; answers survive because they are keyed by question id)
```

Open the page in Chrome or Edge, click **Connect folder** once, choose the `inquisitor` folder, and
answer. Progress is never lost: it is rewritten to `answers.md` within a second and restored on
reopening. **Finish** marks the file FINAL.

```
python scripts/build.py inquisitor/questions.json     build the page (validates first)
python scripts/build.py --status                      counts and open blockers from answers.md
python install.py                                     install for Claude, Codex, Cline, Copilot
python -m unittest discover -s tests                  local suite
```

Python 3.8+ and the standard library only; the page has no network dependencies.
See `SKILL.md` for the procedure and the spec format, `examples/questions.example.json` for a sample.
