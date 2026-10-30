# Acme example project

A made-up company, to show what a project that adopts agent-steddy looks like.
The tests in `tests/test_example_project.py` run the real hook scripts and the `agent-steddy` command against it.
It has no product code, only the files that the kit reads and writes.

| Path | What it is |
| --- | --- |
| `.claude/agent-steddy.json` | The project config, see the [config reference](../../docs/config.md). |
| `.claude/agents/` | Four agents filled in from the [templates](../../templates/README.md): `acme-web`, `acme-auditor`, `acme-verifier` and `acme-docs`. |
| `docs/agents/roles/` | One role card for each agent. |

The config sets these rules:

- Only agent types that match `acme-*` start, and each runs on the model its file names: `sonnet`, except `acme-docs` on `haiku`.
- `acme-auditor` writes only under `docs/reviews/`.
- Every `acme-*` hand-back must name a status (`PASS`, `ISSUES` or `BLOCKED`), a verification level, a retro line and a resources line, or it is blocked once.
- `git push`, `make deploy` and `make deploy-web` need the owner's confirmation when a subagent runs them, `npm publish` and `pnpm publish` always do, and `acme-cli config push` is denied.
- The resume notes of `agent-steddy pause` stay in the local state, since `resume.folder` is `null`; set it to a folder such as `docs/agents/resume` to keep them in the repo.
- The premise nudge stays on: `nudges.premise` is `true`, which is the default, so a command that fails twice in a row in a session gets the line that says to test the premise.
- The records go to `docs/agents/`, which does not exist until the first `agent-steddy record` or `agent-steddy metrics log` creates it; a rule promoted with `agent-steddy lessons promote` goes into a card of `docs/agents/roles/`, or into `docs/agents/walls.md` with `--to walls`.

The config names `make verify` as the verify command; the example has no Makefile because it has no product code.
To try it, copy this folder somewhere else, make the copy a git repo, and start `claude --plugin-dir <path to agent-steddy>` in it.
