from dotenv import load_dotenv
import os

load_dotenv()

import argparse
import json
from pathlib import Path
import sys
from typing import Any

try:
    from scripts.code_intel_common import json_dumps, resolve_codebase_root
except ModuleNotFoundError:
    from code_intel_common import json_dumps, resolve_codebase_root


def usage_log_path(codebase: str | None = None) -> Path:
    configured = os.getenv("CODE_INTEL_MCP_USAGE_LOG")
    if configured:
        return Path(configured).expanduser().resolve()
    return (resolve_codebase_root(codebase) / ".code-intel" / "mcp_usage.jsonl").resolve()


def read_records(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if limit:
        lines = lines[-limit:]
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def summarize(records: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    total_output_tokens = sum(int(row.get("output_estimated_tokens") or 0) for row in records)
    total_without_mcp = sum(int(row.get("without_mcp_estimated_tokens") or 0) for row in records)
    total_saved = max(total_without_mcp - total_output_tokens, 0)
    total_ms = sum(float((row.get("timings_ms") or {}).get("total_ms") or 0) for row in records)

    by_tool: dict[str, dict[str, Any]] = {}
    phase_totals_ms: dict[str, float] = {}
    for row in records:
        timings = row.get("timings_ms") or {}
        for phase, duration in timings.items():
            phase_totals_ms[phase] = round(phase_totals_ms.get(phase, 0.0) + float(duration or 0), 2)

        tool_name = row.get("tool_name") or "unknown"
        bucket = by_tool.setdefault(
            tool_name,
            {
                "calls": 0,
                "output_estimated_tokens": 0,
                "without_mcp_estimated_tokens": 0,
                "estimated_tokens_saved": 0,
                "total_ms": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["output_estimated_tokens"] += int(row.get("output_estimated_tokens") or 0)
        bucket["without_mcp_estimated_tokens"] += int(row.get("without_mcp_estimated_tokens") or 0)
        bucket["estimated_tokens_saved"] += int(row.get("estimated_tokens_saved") or 0)
        bucket["total_ms"] = round(bucket["total_ms"] + float(timings.get("total_ms") or 0), 2)

    return {
        "usage_log": str(path),
        "records": len(records),
        "output_estimated_tokens": total_output_tokens,
        "without_mcp_estimated_tokens": total_without_mcp,
        "estimated_tokens_saved": total_saved,
        "estimated_savings_percent": round((total_saved / total_without_mcp * 100), 2) if total_without_mcp else 0.0,
        "total_duration_ms": round(total_ms, 2),
        "total_duration_seconds": round(total_ms / 1000, 2),
        "phase_totals_ms": phase_totals_ms,
        "by_tool": by_tool,
        "note": "Token counts are heuristic estimates for MCP output vs loading all supported source files.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize MCP token savings and timing telemetry.")
    parser.add_argument("--codebase", help="Path to the umre_ops codebase. Defaults to CODEBASE_ROOT or inferred repo root.")
    parser.add_argument("--log", help="Explicit MCP usage JSONL path. Defaults to CODE_INTEL_MCP_USAGE_LOG or .code-intel/mcp_usage.jsonl.")
    parser.add_argument("--limit", type=int, help="Only summarize the last N records.")
    parser.add_argument("--tail", type=int, default=0, help="Also include the last N raw records.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    path = Path(args.log).expanduser().resolve() if args.log else usage_log_path(args.codebase)
    records = read_records(path, args.limit)
    summary = summarize(records, path)
    if args.tail:
        summary["tail"] = records[-args.tail :]
    print(json_dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
