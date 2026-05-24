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

### 🌪️ Agentic Multi-Agent & Workflow Architecture

This repository has been fully upgraded to a modern **@vudovn/ag-kit** based multi-agent orchestration, multi-layered memory, and dynamic workflow architecture.

#### 👥 7 Expert Agent Personas (`.agent/agents/`)
- **`scout-agent`**: Codebase pathfinder, dependency mapper, and semantic scanning expert.
- **`frappe-architect`**: Custom Desk elements, Single DocTypes, and Frappe bench commands.
- **`accounting-ledger-specialist`**: Statutory accounting plans, journal entry posting rules.
- **`cost-engine-auditor`**: Precise cost component calculation, meal & visa costs formulas.
- **`qa-integrity-validator`**: Gold standard automated tests and server-side checks.
- **`app-cleaner-janitor`**: Safely quarantining codebase debris and caching issues.
- **`localization-expert`**: Turkish translation wrapping and localized context sync.

#### 🧠 3-Tier Persistent Memory (`.agent/memory/`)
1. **Tier 1 (`MEMORY.md`)**: Main workspace log containing current sprint focus and session audits.
2. **Tier 2 (`topics/`)**: Deep domain knowledge (Frappe architecture, statutory accounting, cost formulas).
3. **Tier 3 (`audit_trail.jsonl`)**: Chronological audit trail logs for all operations.

#### 🔗 10 Dynamic Workflows (`.agent/workflows/`)
Workflows are equipped with YAML frontmatter headers to be fully discoverable and runnable by the IDE and Antigravity SDK:
- `/plan` (mandatory agent/workflow assignment)
- `/orchestrate` (subagent spawning, state locks, error exception protocols)
- `/brainstorm` (collaborative conflict resolution)
- `/test` & `/verify` (automated unit/integration tests and statutory integrity checks)
- `/clean` (cache wiping and quarantines)
- `/post` (financial journal postings)
- `/localize` (Turkish translation sync)
- `/scout` & `/import` (code pathfinding and hard-validated excel imports)
```

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
