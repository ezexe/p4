<div align="center">
<img width="480" height="358" alt="AshleyOlsenHalloweenGIFbyFilmeditor" src="https://github.com/user-attachments/assets/da315f32-eff3-460b-9fdc-dacac60767c9" />
</div>

# Contributing to p4

## Native first

p4 uses Claude Code's own settings, hooks, commands and session tools, so a session uses those features rather than a copy p4 builds.

Before building anything, look up whether Claude Code already does it.
Start from the docs index at https://code.claude.com/docs/llms.txt and read every page it names that bears on the behaviour; settings, hooks, slash commands, the session tools of the desktop app, permissions, memory, subagents, skills and plugins are where to begin, not a limit.

- **Claude Code does it:** p4 configures the setting or calls the feature, and builds no copy of it.
- **Claude Code does part of it:** p4 configures the native part and builds only the part that is missing, naming in its commit what the native feature lacks and the page that says so.
- **Claude Code does none of it:** p4 builds it, and the commit names the docs pages that were checked.
- **p4 already has a copy of a native feature:** the copy is replaced by the native feature and deleted, not extended.

The only p4 behaviour kept beside a native one is a part the native feature lacks, and the change that keeps it names the docs page that shows the lack in its commit message or issue comment.
A question the docs, the code or the issue that built a thing can settle is settled that way, not asked, and the commit or issue comment names the source.

## Developing p4 while it is installed

A session that edits p4 runs its development copy with `claude --plugin-dir <clone>/lbiza/plugins/p4-phi --debug`, and with a second `--plugin-dir <clone>/lbiza/plugins/p4-temportal` when it edits p4-temportal.
Live hook behaviour is checked that way from a scratch project, never in the project where p4 is developed, and the debug log names the override of the installed copy.
Each landing names its proof: the clone path and the commit its tests and live checks ran on.
A landing that changes a plugin's files bumps the version in that plugin's `.claude-plugin/plugin.json`, the one file that holds it, since the catalog `.claude-plugin/marketplace.json` at the repository's root carries no version.
An installed copy is a copy in Claude Code's plugin cache, which takes the new version at the next auto-update pass where auto-update is on for `p4-marketplace`, and at `claude plugin update <plugin>@p4-marketplace` otherwise.

## Tests

Every test of the repository is under `tests/`, in the folder named after the plugin whose code it runs, and pytest runs them.
`python -m venv .venv` and then `.venv/bin/python -m pip install --group dev` set the test tools up once in a checkout, with `.venv\Scripts\python.exe` in place of `.venv/bin/python` on Windows.
`.venv/bin/python -m pytest` runs every test, on a worker for each logical processor and eight at most, and `.venv/bin/python -m pytest tests/p4-phi/test_relay.py` runs one file.
[`pyproject.toml`](pyproject.toml) names the tools and pytest's settings.
[`tests/conftest.py`](tests/conftest.py) gives each worker a temp folder, a home and git settings of its own and none of a session's variables, so a run from a Claude Code session sees nothing of that session and spends nothing.
A test file reaches the code it runs by its `SRC` folder, and a test of a new python file goes in `tests/<plugin>/test_<name>.py`.
A hooks module's `register.test.ts` stays beside the module inside its plugin, where `claude plugin test` reads it.
A landing rests on a local run of `python -m pytest` that passes.
GitHub runs the `tests` workflow of [`.github/workflows/tests.yml`](.github/workflows/tests.yml) on every pull request and every push to `main`, with no credentials: its `pytest` job runs every test on a Windows runner, and its `plugins` job runs `claude plugin validate --strict` on the catalog and on each plugin and `claude plugin test` on each plugin's hooks module.
