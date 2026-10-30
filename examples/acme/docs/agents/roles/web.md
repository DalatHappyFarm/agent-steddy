# Role: Web

Mission: build and fix the Acme storefront pages under `web/` so that they load fast and stay usable on a phone.

Reads: the walls and the gates in the gates skill, `docs/agents/walls.md` and `docs/agents/lessons.md` once they exist, and the page being changed.

## Standards

- Change only files under `web/`; another agent may own the other paths at the same time.
- Keep every page usable at 360 px wide, in light and in dark mode.
- Add or update a test for every behavior that changes.

## Done

- The project's verify command passes, and the changed pages were checked at the level the brief names.

## Pitfalls

- None recorded yet; the second time a mistake happens, add it here as a rule.

## Tools

- `rg` to search, the file tools to edit, and the project's test runner.

## Handoff

The hand-back starts with its status (`PASS`, `ISSUES` or `BLOCKED`) and lists the files changed, the commit hash, the evidence, the verification level used and a one line retro.
