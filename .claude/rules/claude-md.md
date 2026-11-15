---
paths:
  - "CLAUDE.md"
  - ".claude/**"
---

# Keeping CLAUDE.md short

`CLAUDE.md` loads in every session, so every line costs context. CI (`claude-md.yml`) fails when it passes 150 lines or a rule file passes 80.

- **Root `CLAUDE.md`:** commands, conventions, and rules Claude would get wrong anywhere in the repo. One line each.
- **`.claude/rules/<area>.md` with `paths:`:** rules for one area. Add a file rather than growing the root, and list it in the root's rules line.
- **`README.md`:** how-tos for people.
- **Linear:** decisions and why, history, what was tried: the story, and the Architecture doc for decisions that span the system.

Before adding a line, ask: would Claude get this wrong without it? If not, leave it out.

Never add file lists or directory tours, history or ticket numbers, anything lint, a type check or a test already enforces, or copies of README how-tos. A rule may point to its story for the why, e.g. "(why: FPL-86)".
