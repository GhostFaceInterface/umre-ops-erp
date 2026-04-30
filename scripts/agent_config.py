from dotenv import load_dotenv
import os

load_dotenv()

import argparse
import json
from pathlib import Path
from typing import Any

SERVER_NAME = "umre_ops_code_intelligence"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def launcher_path(root: Path) -> Path:
    return root / "scripts" / "run_mcp_server.sh"


def mcp_server_definition(root: Path, *, absolute: bool = True) -> dict[str, Any]:
    launcher = launcher_path(root)
    launcher_arg = str(launcher if absolute else Path("scripts/run_mcp_server.sh"))
    env: dict[str, str] = {"CODEBASE_ROOT": str(root) if absolute else "."}

    model_name = os.getenv("CODE_INTEL_MODEL_NAME")
    model_revision = os.getenv("CODE_INTEL_MODEL_REVISION")
    if model_name:
        env["CODE_INTEL_MODEL_NAME"] = model_name
    if model_revision:
        env["CODE_INTEL_MODEL_REVISION"] = model_revision

    return {
        "command": "/bin/bash",
        "args": [launcher_arg],
        "env": env,
    }


def cursor_config(root: Path, *, absolute: bool = True) -> dict[str, Any]:
    return {"mcpServers": {SERVER_NAME: mcp_server_definition(root, absolute=absolute)}}


def generic_config(root: Path) -> dict[str, Any]:
    return {
        "name": SERVER_NAME,
        "transport": "stdio",
        "description": "Supabase pgvector-backed code intelligence tools for umre_ops.",
        "server": mcp_server_definition(root, absolute=True),
        "tools": [
            "search_code",
            "get_file",
            "get_function",
            "code_index_status",
        ],
    }


def toml_string(value: str) -> str:
    return json.dumps(value)


def toml_array(values: list[str]) -> str:
    return "[" + ", ".join(toml_string(value) for value in values) + "]"


def codex_toml(root: Path) -> str:
    definition = mcp_server_definition(root, absolute=True)
    lines = [
        f"[mcp_servers.{SERVER_NAME}]",
        f"command = {toml_string(definition['command'])}",
        f"args = {toml_array(definition['args'])}",
        "",
        f"[mcp_servers.{SERVER_NAME}.env]",
    ]
    for key, value in sorted(definition["env"].items()):
        lines.append(f"{key} = {toml_string(value)}")
    return "\n".join(lines) + "\n"


def write_cursor_config(root: Path) -> Path:
    target = root / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cursor_config(root, absolute=False), indent=2) + "\n", encoding="utf-8")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print MCP agent configs for umre_ops code intelligence.")
    parser.add_argument(
        "--format",
        choices=("cursor", "codex", "generic"),
        default="generic",
        help="Agent config format to print.",
    )
    parser.add_argument(
        "--write-cursor",
        action="store_true",
        help="Write project-local .cursor/mcp.json using repo-relative launcher path.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = repo_root()

    if args.write_cursor:
        print(write_cursor_config(root))
        return 0

    if args.format == "cursor":
        print(json.dumps(cursor_config(root), indent=2))
    elif args.format == "codex":
        print(codex_toml(root), end="")
    else:
        print(json.dumps(generic_config(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
