### Umre Ops

Umre operasyon sistemi

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench install-app umre_ops
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/umre_ops
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### Codex agent architecture

The repository includes a project-scoped, token-conscious Codex setup:

- `AGENTS.md`: durable safety, validation, and delegation rules
- `.codex/config.toml`: subagent concurrency and low-cost defaults
- `.codex/agents/`: focused explorer, Frappe, finance, test, implementation, and review roles
- `.agents/skills/orchestrate-umre-ops/`: S0–S3 workflow that keeps simple tasks single-agent and uses a single writer for complex changes

Invoke `$orchestrate-umre-ops` for repository health audits, accounting-sensitive changes, migrations, or work spanning multiple layers. Straightforward one-file changes intentionally stay in the main agent.

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
