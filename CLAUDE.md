# ezexe/p4

The p4 marketplace: two Claude Code plugins, p4-phi and p4-temportal, and the pages that say what they do.

- The catalog is `.claude-plugin/marketplace.json`. Each plugin is a folder of `lbiza/plugins`, with its
  `.claude-plugin/plugin.json`, its `hooks`, its `scripts` and its `skills`.
- The tests are in `lbiza/tests`, a folder for each plugin. Run them from `lbiza` with
  `python -m pytest tests/<plugin>/<file> -q -p no:cacheprovider`; `lbiza/pyproject.toml` says what to install.
- `register.ts` of each plugin is its hooks module, type-checked by `claude plugin validate <path> --strict` and run by
  `claude plugin test <path>`.
- `p4conf.py` has one copy in each plugin, and the two stay the same byte for byte.
- The pages are in `docs`, and `README.md` links them.
- Read the skill `native` before a native feature of Claude Code is built on, and when ezexe corrects how a p4
  plugin behaves.

See more: https://code.claude.com/docs/en/memory.md
