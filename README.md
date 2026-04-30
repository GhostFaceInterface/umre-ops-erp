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

### AI Code Intelligence

This repo includes a Supabase pgvector-backed code intelligence system for AI agents.

Default production embedding model:

```bash
BAAI/bge-code-v1
```

Setup:

```bash
python3 -m venv .venv-code-intel
source .venv-code-intel/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with Supabase credentials, then generate the schema SQL:

```bash
python scripts/index_codebase.py --print-sql
```

When migrating from an older embedding model, first print and run the reset SQL in Supabase SQL Editor:

```bash
python scripts/index_codebase.py --print-reset-sql
```

Then run the schema SQL and index:

```bash
python scripts/index_codebase.py
python scripts/search.py "dashboard logic"
```

`index_codebase.py` is incremental by default. On each run it compares indexed
`metadata.file_path` + `content_hash` against the current working tree, deletes
stale chunks for changed/removed files, and inserts only the chunks that still
need indexing. To fall back to append-only hash deduplication:

```bash
python scripts/index_codebase.py --no-incremental
```

For daily syncs, validation search is disabled by default so unchanged runs do
not load the embedding model. Run validation explicitly when needed:

```bash
python scripts/index_codebase.py --test-query "dashboard logic"
```

If local memory allows it, embedding can be tuned with a larger batch size:

```bash
CODE_INTEL_EMBEDDING_BATCH_SIZE=32 python scripts/index_codebase.py
```

The HTTP server is only for direct local debugging with curl/browser:

```bash
python scripts/server.py --host 127.0.0.1 --port 8765
```

Agent integration is intentionally modular. The MCP server is the stable core;
Cursor, Codex, and other clients are only thin config adapters around the same
launcher.

Canonical files:

- `scripts/mcp_server.py` — MCP tools and Supabase-backed retrieval.
- `scripts/run_mcp_server.sh` — shared stdio launcher used by agents.
- `scripts/agent_config.py` — prints agent-specific config snippets.
- `config/agents/code_intelligence_mcp.json` — generic manifest.

For MCP-capable agents, use the shared stdio launcher:

```bash
/bin/bash scripts/run_mcp_server.sh
```

The project-local Cursor config is already provided at `.cursor/mcp.json`.
It contains no Supabase credentials; those are loaded from `.env` by the Python
scripts. Regenerate it if needed:

```bash
python scripts/agent_config.py --write-cursor
```

Print a Cursor JSON config:

```bash
python scripts/agent_config.py --format cursor
```

Print a Codex TOML config snippet:

```bash
python scripts/agent_config.py --format codex
```

Print a generic MCP manifest for another agent:

```bash
python scripts/agent_config.py --format generic
```

Example Cursor config:

```json
{
  "mcpServers": {
    "umre_ops_code_intelligence": {
      "command": "/bin/bash",
      "args": [
        "scripts/run_mcp_server.sh"
      ],
      "env": {
        "CODEBASE_ROOT": "."
      }
    }
  }
}
```

Example Codex config snippet:

```toml
[mcp_servers.umre_ops_code_intelligence]
command = "/bin/bash"
args = ["/absolute/path/to/umre_ops/scripts/run_mcp_server.sh"]

[mcp_servers.umre_ops_code_intelligence.env]
CODEBASE_ROOT = "/absolute/path/to/umre_ops"
```

The MCP tools are:

- `search_code(query, limit)`
- `get_file(path, max_chars)`
- `get_function(name, limit, max_chars)`
- `code_index_status()`

Do not mix embeddings from different models in the same vector table. Changing `CODE_INTEL_MODEL_NAME` requires resetting the vector table and reindexing.

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
