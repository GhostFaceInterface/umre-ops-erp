from dotenv import load_dotenv
import os

load_dotenv()

import argparse
import json
from pathlib import Path
import sys
from typing import Any

try:
    from scripts.code_intel_common import (
        estimate_practical_agent_tokens,
        json_dumps,
        resolve_codebase_root,
    )
except ModuleNotFoundError:
    from code_intel_common import estimate_practical_agent_tokens, json_dumps, resolve_codebase_root


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
    total_output_tokens = sum(int(row.get("mcp_output_estimated_tokens") or row.get("output_estimated_tokens") or 0) for row in records)
    total_full_codebase = sum(int(row.get("full_codebase_baseline_tokens") or row.get("without_mcp_estimated_tokens") or 0) for row in records)
    total_practical = 0
    for row in records:
        output_tokens = int(row.get("mcp_output_estimated_tokens") or row.get("output_estimated_tokens") or 0)
        full_tokens = int(row.get("full_codebase_baseline_tokens") or row.get("without_mcp_estimated_tokens") or 0)
        total_practical += int(
            row.get("practical_agent_baseline_estimated_tokens")
            or estimate_practical_agent_tokens(row.get("tool_name") or "unknown", output_tokens, full_tokens)
        )
    total_max_saved = max(total_full_codebase - total_output_tokens, 0)
    total_practical_saved = max(total_practical - total_output_tokens, 0)
    total_ms = sum(float((row.get("timings_ms") or {}).get("total_ms") or 0) for row in records)

    by_tool: dict[str, dict[str, Any]] = {}
    phase_totals_ms: dict[str, float] = {}
    for row in records:
        timings = row.get("timings_ms") or {}
        for phase, duration in timings.items():
            phase_totals_ms[phase] = round(phase_totals_ms.get(phase, 0.0) + float(duration or 0), 2)

        tool_name = row.get("tool_name") or "unknown"
        output_tokens = int(row.get("mcp_output_estimated_tokens") or row.get("output_estimated_tokens") or 0)
        full_tokens = int(row.get("full_codebase_baseline_tokens") or row.get("without_mcp_estimated_tokens") or 0)
        practical_tokens = int(
            row.get("practical_agent_baseline_estimated_tokens")
            or estimate_practical_agent_tokens(tool_name, output_tokens, full_tokens)
        )
        bucket = by_tool.setdefault(
            tool_name,
            {
                "calls": 0,
                "mcp_output_estimated_tokens": 0,
                "full_codebase_baseline_tokens": 0,
                "practical_agent_baseline_estimated_tokens": 0,
                "max_context_tokens_avoided": 0,
                "practical_estimated_tokens_saved": 0,
                "total_ms": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["mcp_output_estimated_tokens"] += output_tokens
        bucket["full_codebase_baseline_tokens"] += full_tokens
        bucket["practical_agent_baseline_estimated_tokens"] += practical_tokens
        bucket["max_context_tokens_avoided"] += max(full_tokens - output_tokens, 0)
        bucket["practical_estimated_tokens_saved"] += max(practical_tokens - output_tokens, 0)
        bucket["total_ms"] = round(bucket["total_ms"] + float(timings.get("total_ms") or 0), 2)

    return {
        "usage_log": str(path),
        "records": len(records),
        "mcp_output_estimated_tokens": total_output_tokens,
        "full_codebase_baseline_tokens": total_full_codebase,
        "practical_agent_baseline_estimated_tokens": total_practical,
        "max_context_tokens_avoided": total_max_saved,
        "practical_estimated_tokens_saved": total_practical_saved,
        "max_context_savings_percent": round((total_max_saved / total_full_codebase * 100), 2) if total_full_codebase else 0.0,
        "practical_savings_percent": round((total_practical_saved / total_practical * 100), 2) if total_practical else 0.0,
        # Backward-compatible aliases.
        "output_estimated_tokens": total_output_tokens,
        "without_mcp_estimated_tokens": total_full_codebase,
        "estimated_tokens_saved": total_max_saved,
        "estimated_savings_percent": round((total_max_saved / total_full_codebase * 100), 2) if total_full_codebase else 0.0,
        "total_duration_ms": round(total_ms, 2),
        "total_duration_seconds": round(total_ms / 1000, 2),
        "phase_totals_ms": phase_totals_ms,
        "by_tool": by_tool,
        "note": (
            "Token counts are heuristic estimates. full_codebase_baseline_tokens is a theoretical "
            "upper baseline; practical_agent_baseline_estimated_tokens is the more realistic "
            "Codex/Cursor-style comparison."
        ),
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
