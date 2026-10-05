from __future__ import annotations

import shutil
from pathlib import Path


SKILL_NAME = "scribe"
SOURCE = Path(__file__).resolve().parent
TARGETS = (
    Path.home() / ".claude" / "skills" / SKILL_NAME,
    Path.home() / ".agents" / "skills" / SKILL_NAME,
    Path.home() / ".cline" / "skills" / SKILL_NAME,
    Path.home() / ".copilot" / "skills" / SKILL_NAME,
)


def copy_skill(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SOURCE,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def main() -> int:
    print(f"Installing {SKILL_NAME} from {SOURCE}")
    for target in TARGETS:
        copy_skill(target)
        print(f"  installed: {target}")
    print("Done. Restart active CLI sessions so they reload their skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
