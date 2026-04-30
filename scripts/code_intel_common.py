from dotenv import load_dotenv
import os

load_dotenv()

import argparse
import ast
import hashlib
import importlib.metadata as importlib_metadata
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_NAME = "umre_ops"
DEFAULT_MODEL_NAME = "BAAI/bge-code-v1"
FALLBACK_MODEL_NAME = "nomic-ai/CodeRankEmbed"
MODEL_NAME = os.getenv("CODE_INTEL_MODEL_NAME", DEFAULT_MODEL_NAME)
MODEL_REVISION = os.getenv("CODE_INTEL_MODEL_REVISION")
DEFAULT_EMBEDDING_DIMENSION = int(os.getenv("CODE_INTEL_EMBEDDING_DIMENSION", "1536"))
DEFAULT_MATCH_COUNT = 5
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
CODEBASE_ROOT = os.getenv("CODEBASE_ROOT")

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".json", ".md", ".yaml", ".yml"}
IGNORED_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", ".venv-code-intel", "env", "ENV"}
MAX_FILE_BYTES = int(os.getenv("CODE_INTEL_MAX_FILE_BYTES", str(1024 * 1024)))
MIN_CHUNK_TOKENS = int(os.getenv("CODE_INTEL_MIN_CHUNK_TOKENS", "500"))
MAX_CHUNK_TOKENS = int(os.getenv("CODE_INTEL_MAX_CHUNK_TOKENS", "1000"))

LOGGER = logging.getLogger("code_intel")


SQL_SCHEMA_TEMPLATE = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS code_chunks (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding VECTOR({dimension}) NOT NULL,
    metadata JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_revision TEXT,
    embedding_dimension INT NOT NULL,
    indexed_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (content_hash, model_name)
);

CREATE TABLE IF NOT EXISTS code_index_runs (
    id BIGSERIAL PRIMARY KEY,
    project TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_revision TEXT,
    embedding_dimension INT NOT NULL,
    status TEXT NOT NULL,
    files_processed INT DEFAULT 0,
    chunks_created INT DEFAULT 0,
    rows_inserted INT DEFAULT 0,
    rows_skipped INT DEFAULT 0,
    db_rows INT,
    error TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_code_chunks_embedding
ON code_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE OR REPLACE FUNCTION match_code_chunks (
    query_embedding VECTOR({dimension}),
    match_count INT DEFAULT 5,
    query_model_name TEXT DEFAULT '{model_name}'
)
RETURNS TABLE (
    id BIGINT,
    content TEXT,
    metadata JSONB,
    similarity FLOAT
)
LANGUAGE SQL
AS $$
SELECT
    id,
    content,
    metadata,
    1 - (embedding <=> query_embedding) AS similarity
FROM code_chunks
WHERE model_name = query_model_name
ORDER BY embedding <=> query_embedding
LIMIT match_count;
$$;
""".strip()


RESET_SQL_TEMPLATE = """
DROP FUNCTION IF EXISTS match_code_chunks(vector, INT, TEXT);
DROP FUNCTION IF EXISTS match_code_chunks(vector, INT);
DROP TABLE IF EXISTS code_index_runs;
DROP TABLE IF EXISTS code_chunks;
""".strip()


@dataclass(frozen=True)
class CodeChunk:
    content: str
    metadata: dict[str, Any]
    content_hash: str


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")
    if not verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("httpcore.http11").setLevel(logging.WARNING)


def set_model_config(model_name: str | None = None, model_revision: str | None = None) -> None:
    global MODEL_NAME, MODEL_REVISION
    if model_name:
        MODEL_NAME = model_name
    if model_revision is not None:
        MODEL_REVISION = model_revision or None


def active_model_name() -> str:
    return MODEL_NAME


def active_model_revision() -> str | None:
    return MODEL_REVISION


def load_environment() -> None:
    load_dotenv()


def get_supabase_client() -> Any:
    load_environment()
    from supabase import create_client

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def get_embedding_model() -> Any:
    from sentence_transformers import SentenceTransformer

    validate_model_dependencies(MODEL_NAME)
    kwargs: dict[str, Any] = {"trust_remote_code": True}
    if MODEL_REVISION:
        kwargs["revision"] = MODEL_REVISION
    model_kwargs = model_load_kwargs(MODEL_NAME)
    if model_kwargs:
        kwargs["model_kwargs"] = model_kwargs

    return SentenceTransformer(MODEL_NAME, **kwargs)


def validate_model_dependencies(model_name: str) -> None:
    transformers_version = importlib_metadata.version("transformers")
    transformers_major = int(transformers_version.split(".", 1)[0])
    if transformers_major >= 5:
        raise RuntimeError(
            "Incompatible transformers version detected: "
            f"{transformers_version}. This project currently pins Transformers 4.x "
            "for the selected code embedding stack. Run: "
            "pip install --force-reinstall -r requirements.txt"
        )

    if model_name == "jinaai/jina-embeddings-v2-base-code":
        import transformers.pytorch_utils as pytorch_utils

        if not hasattr(pytorch_utils, "find_pruneable_heads_and_indices"):
            raise RuntimeError(
                "Incompatible transformers version detected: "
                f"{transformers_version}. The Jina embedding model requires "
                "Transformers 4.x because its remote code imports "
                "'find_pruneable_heads_and_indices'. Run: "
                "pip install --force-reinstall 'transformers>=4.41.0,<5.0.0'"
            )


def model_load_kwargs(model_name: str) -> dict[str, Any]:
    torch_dtype = os.getenv("CODE_INTEL_TORCH_DTYPE", "")
    if not torch_dtype:
        return {}

    import torch

    dtype_map = {
        "float16": torch.float16,
        "fp16": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    if torch_dtype not in dtype_map:
        raise RuntimeError(
            f"Unsupported CODE_INTEL_TORCH_DTYPE={torch_dtype!r}. "
            "Use float16, bfloat16, or float32."
        )
    return {"torch_dtype": dtype_map[torch_dtype]}


def query_prompt(model_name: str = MODEL_NAME) -> str | None:
    if model_name == DEFAULT_MODEL_NAME:
        instruction = os.getenv(
            "CODE_INTEL_QUERY_INSTRUCTION",
            "Given a question in text, retrieve code snippets, files, or functions that are relevant to the question.",
        )
        return f"<instruct>{instruction}\n<query>"
    if model_name == FALLBACK_MODEL_NAME:
        return "Represent this query for searching relevant code: "
    return None


def encode_texts(model: Any, texts: list[str], batch_size: int = 16) -> list[list[float]]:
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=batch_size,
        show_progress_bar=False,
    )
    return [embedding.tolist() for embedding in embeddings]


def encode_query(model: Any, query: str) -> list[float]:
    prompt = query_prompt(MODEL_NAME)
    if prompt:
        embedding = model.encode(query, prompt=prompt, normalize_embeddings=True)
    else:
        embedding = model.encode(query, normalize_embeddings=True)
    return embedding.tolist()


def detect_embedding_dimension(model: Any) -> int:
    return len(encode_query(model, "dimension probe"))


def schema_sql(dimension: int = DEFAULT_EMBEDDING_DIMENSION, model_name: str = MODEL_NAME) -> str:
    return SQL_SCHEMA_TEMPLATE.format(dimension=dimension, model_name=model_name.replace("'", "''"))


def reset_schema_sql() -> str:
    return RESET_SQL_TEMPLATE


def initialize_database_schema(dimension: int) -> None:
    """Run pgvector DDL through the direct Postgres URL when available.

    Supabase's REST client does not expose arbitrary SQL execution. Production
    setup should therefore provide SUPABASE_DB_URL or DATABASE_URL for schema
    provisioning, while data writes/searches use the service-role Supabase API.
    """

    db_url = SUPABASE_DB_URL or DATABASE_URL
    if not db_url:
        raise RuntimeError(
            "SUPABASE_DB_URL or DATABASE_URL is required for --init-db. "
            "Run --print-sql to apply the schema manually in Supabase SQL Editor."
        )

    import psycopg

    with psycopg.connect(db_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(schema_sql(dimension, MODEL_NAME))
        connection.commit()


def resolve_codebase_root(cli_path: str | None = None) -> Path:
    if cli_path:
        resolved_cli_path = Path(cli_path).expanduser().resolve()
        if not resolved_cli_path.exists():
            raise FileNotFoundError(f"Codebase path does not exist: {resolved_cli_path}")
        if (resolved_cli_path / "umre_ops").exists() or resolved_cli_path.name == PROJECT_NAME:
            return resolved_cli_path
        raise FileNotFoundError(f"Path does not look like the umre_ops codebase: {resolved_cli_path}")

    candidates = []
    if CODEBASE_ROOT:
        candidates.append(Path(CODEBASE_ROOT))
    candidates.extend(
        [
            Path.cwd() / "../frappe-bench/apps/umre_ops",
            Path(__file__).resolve().parents[1],
            Path.cwd(),
        ]
    )

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if not resolved.exists():
            continue
        if (resolved / "umre_ops").exists() or resolved.name == PROJECT_NAME:
            return resolved

    raise FileNotFoundError(
        "Could not locate umre_ops codebase. Set CODEBASE_ROOT or pass --codebase."
    )


def infer_language(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".js", ".ts", ".tsx"}:
        return {".js": "javascript", ".ts": "typescript", ".tsx": "tsx"}[suffix]
    if suffix == ".json":
        return "json"
    if suffix == ".md":
        return "markdown"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    return suffix.lstrip(".")


def should_ignore(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or should_ignore(path.relative_to(root)):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                LOGGER.warning("Skipping large file: %s", path)
                continue
        except OSError as exc:
            LOGGER.warning("Skipping unreadable file %s: %s", path, exc)
            continue
        files.append(path)
    return sorted(files)


TOKEN_RE = re.compile(r"\w+|[^\s\w]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    return len(TOKEN_RE.findall(text))


PRACTICAL_AGENT_BASELINE_TOKENS = {
    "search_code": 12000,
    "get_file": 6000,
    "get_function": 10000,
    "code_index_status": 2000,
    "estimate_context_savings": 15000,
    "mcp_usage_summary": 2000,
    "project_cleanup_context": 25000,
}

PRACTICAL_AGENT_CONTEXT_MULTIPLIER = {
    "search_code": 6,
    "get_file": 2,
    "get_function": 4,
    "code_index_status": 2,
    "estimate_context_savings": 3,
    "mcp_usage_summary": 2,
    "project_cleanup_context": 3,
}


def estimate_practical_agent_tokens(
    tool_name: str,
    output_tokens: int,
    full_codebase_tokens: int,
) -> int:
    """Estimate a realistic non-MCP agent context budget for one tool call.

    This is intentionally a heuristic. The full-codebase token count is a hard
    upper baseline, but normal agents usually inspect search results, nearby
    files, and supporting context rather than loading every supported source
    file. This estimate gives telemetry a more honest comparison point.
    """

    base = PRACTICAL_AGENT_BASELINE_TOKENS.get(tool_name, 8000)
    multiplier = PRACTICAL_AGENT_CONTEXT_MULTIPLIER.get(tool_name, 3)
    estimate = max(output_tokens, base, output_tokens * multiplier)
    return min(estimate, full_codebase_tokens) if full_codebase_tokens else estimate


def estimate_codebase_tokens(root: Path) -> dict[str, int]:
    files = 0
    characters = 0
    estimated_tokens = 0
    for path in iter_source_files(root):
        try:
            content = read_text(path)
        except Exception:
            continue
        files += 1
        characters += len(content)
        estimated_tokens += estimate_tokens(content)
    return {
        "files": files,
        "characters": characters,
        "estimated_tokens": estimated_tokens,
    }


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def make_chunk(
    *,
    content: str,
    path: Path,
    root: Path,
    chunk_index: int,
    language: str,
    symbol_names: list[str] | None = None,
    symbol_type: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> CodeChunk:
    clean_content = content.strip()
    metadata: dict[str, Any] = {
        "file_path": str(path.relative_to(root)),
        "file_type": path.suffix.lower(),
        "chunk_index": chunk_index,
        "language": language,
        "project": PROJECT_NAME,
    }
    if symbol_names:
        metadata["symbol_names"] = symbol_names
    if symbol_type:
        metadata["symbol_type"] = symbol_type
    if start_line is not None:
        metadata["start_line"] = start_line
    if end_line is not None:
        metadata["end_line"] = end_line
    return CodeChunk(content=clean_content, metadata=metadata, content_hash=content_hash(clean_content))


def split_large_text(content: str, max_tokens: int = MAX_CHUNK_TOKENS) -> list[tuple[str, int, int]]:
    lines = content.splitlines(keepends=True)
    chunks: list[tuple[str, int, int]] = []
    current: list[str] = []
    current_start = 1
    token_count = 0

    for index, line in enumerate(lines, start=1):
        line_tokens = estimate_tokens(line)
        if current and token_count + line_tokens > max_tokens:
            chunks.append(("".join(current), current_start, index - 1))
            current = [line]
            current_start = index
            token_count = line_tokens
        else:
            if not current:
                current_start = index
            current.append(line)
            token_count += line_tokens

    if current:
        chunks.append(("".join(current), current_start, current_start + len(current) - 1))
    return chunks


def chunk_text_regions(
    *,
    content: str,
    path: Path,
    root: Path,
    chunk_index_start: int,
    language: str,
) -> tuple[list[CodeChunk], int]:
    chunks: list[CodeChunk] = []
    index = chunk_index_start
    for text, start_line, end_line in split_large_text(content):
        if text.strip():
            chunks.append(
                make_chunk(
                    content=text,
                    path=path,
                    root=root,
                    chunk_index=index,
                    language=language,
                    start_line=start_line,
                    end_line=end_line,
                )
            )
            index += 1
    return chunks, index


def chunk_python_file(path: Path, root: Path, content: str) -> list[CodeChunk]:
    language = "python"
    lines = content.splitlines(keepends=True)
    chunks: list[CodeChunk] = []
    chunk_index = 0

    try:
        tree = ast.parse(content)
    except SyntaxError:
        chunks, _ = chunk_text_regions(
            content=content,
            path=path,
            root=root,
            chunk_index_start=0,
            language=language,
        )
        return chunks

    top_level = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and hasattr(node, "lineno")
        and hasattr(node, "end_lineno")
    ]
    top_level.sort(key=lambda node: node.lineno)

    cursor_line = 1
    for node in top_level:
        if node.lineno > cursor_line:
            leading = "".join(lines[cursor_line - 1 : node.lineno - 1])
            text_chunks, chunk_index = chunk_text_regions(
                content=leading,
                path=path,
                root=root,
                chunk_index_start=chunk_index,
                language=language,
            )
            chunks.extend(text_chunks)

        node_content = "".join(lines[node.lineno - 1 : node.end_lineno])
        symbol_type = "class" if isinstance(node, ast.ClassDef) else "function"
        symbol_names = [node.name]
        if estimate_tokens(node_content) <= MAX_CHUNK_TOKENS:
            chunks.append(
                make_chunk(
                    content=node_content,
                    path=path,
                    root=root,
                    chunk_index=chunk_index,
                    language=language,
                    symbol_names=symbol_names,
                    symbol_type=symbol_type,
                    start_line=node.lineno,
                    end_line=node.end_lineno,
                )
            )
            chunk_index += 1
        elif isinstance(node, ast.ClassDef):
            method_nodes = [
                child
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                and hasattr(child, "lineno")
                and hasattr(child, "end_lineno")
            ]
            if method_nodes:
                header = "".join(lines[node.lineno - 1 : method_nodes[0].lineno - 1])
                if header.strip():
                    chunks.append(
                        make_chunk(
                            content=header,
                            path=path,
                            root=root,
                            chunk_index=chunk_index,
                            language=language,
                            symbol_names=[node.name],
                            symbol_type="class_header",
                            start_line=node.lineno,
                            end_line=method_nodes[0].lineno - 1,
                        )
                    )
                    chunk_index += 1
                for method in method_nodes:
                    method_content = "".join(lines[method.lineno - 1 : method.end_lineno])
                    if estimate_tokens(method_content) <= MAX_CHUNK_TOKENS:
                        chunks.append(
                            make_chunk(
                                content=method_content,
                                path=path,
                                root=root,
                                chunk_index=chunk_index,
                                language=language,
                                symbol_names=[f"{node.name}.{method.name}", method.name],
                                symbol_type="method",
                                start_line=method.lineno,
                                end_line=method.end_lineno,
                            )
                        )
                        chunk_index += 1
                    else:
                        for part, start, end in split_large_text(method_content):
                            chunks.append(
                                make_chunk(
                                    content=part,
                                    path=path,
                                    root=root,
                                    chunk_index=chunk_index,
                                    language=language,
                                    symbol_names=[f"{node.name}.{method.name}", method.name],
                                    symbol_type="method",
                                    start_line=method.lineno + start - 1,
                                    end_line=method.lineno + end - 1,
                                )
                            )
                            chunk_index += 1
            else:
                for part, start, end in split_large_text(node_content):
                    chunks.append(
                        make_chunk(
                            content=part,
                            path=path,
                            root=root,
                            chunk_index=chunk_index,
                            language=language,
                            symbol_names=symbol_names,
                            symbol_type=symbol_type,
                            start_line=node.lineno + start - 1,
                            end_line=node.lineno + end - 1,
                        )
                    )
                    chunk_index += 1
        else:
            for part, start, end in split_large_text(node_content):
                chunks.append(
                    make_chunk(
                        content=part,
                        path=path,
                        root=root,
                        chunk_index=chunk_index,
                        language=language,
                        symbol_names=symbol_names,
                        symbol_type=symbol_type,
                        start_line=node.lineno + start - 1,
                        end_line=node.lineno + end - 1,
                    )
                )
                chunk_index += 1
        cursor_line = node.end_lineno + 1

    if cursor_line <= len(lines):
        tail = "".join(lines[cursor_line - 1 :])
        text_chunks, chunk_index = chunk_text_regions(
            content=tail,
            path=path,
            root=root,
            chunk_index_start=chunk_index,
            language=language,
        )
        chunks.extend(text_chunks)

    return chunks


JS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+default\s+|export\s+|async\s+)*"
    r"(?:(function)\s+([A-Za-z_$][\w$]*)|"
    r"(class)\s+([A-Za-z_$][\w$]*)|"
    r"(?:(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>))"
)


def find_js_block_end(lines: list[str], start_index: int) -> int:
    depth = 0
    seen_open = False
    for index in range(start_index, len(lines)):
        line = lines[index]
        depth += line.count("{")
        if "{" in line:
            seen_open = True
        depth -= line.count("}")
        if seen_open and depth <= 0:
            return index
        if not seen_open and line.rstrip().endswith(";"):
            return index
    return start_index


def chunk_javascript_like_file(path: Path, root: Path, content: str, language: str) -> list[CodeChunk]:
    lines = content.splitlines(keepends=True)
    chunks: list[CodeChunk] = []
    chunk_index = 0
    cursor = 0

    index = 0
    while index < len(lines):
        match = JS_SYMBOL_RE.match(lines[index])
        if not match:
            index += 1
            continue

        if index > cursor:
            leading = "".join(lines[cursor:index])
            text_chunks, chunk_index = chunk_text_regions(
                content=leading,
                path=path,
                root=root,
                chunk_index_start=chunk_index,
                language=language,
            )
            chunks.extend(text_chunks)

        end = find_js_block_end(lines, index)
        block = "".join(lines[index : end + 1])
        symbol_name = match.group(2) or match.group(4) or match.group(5)
        symbol_type = "class" if match.group(3) else "function"

        if estimate_tokens(block) <= MAX_CHUNK_TOKENS:
            chunks.append(
                make_chunk(
                    content=block,
                    path=path,
                    root=root,
                    chunk_index=chunk_index,
                    language=language,
                    symbol_names=[symbol_name] if symbol_name else None,
                    symbol_type=symbol_type,
                    start_line=index + 1,
                    end_line=end + 1,
                )
            )
            chunk_index += 1
        else:
            for part, start, part_end in split_large_text(block):
                chunks.append(
                    make_chunk(
                        content=part,
                        path=path,
                        root=root,
                        chunk_index=chunk_index,
                        language=language,
                        symbol_names=[symbol_name] if symbol_name else None,
                        symbol_type=symbol_type,
                        start_line=index + start,
                        end_line=index + part_end,
                    )
                )
                chunk_index += 1
        cursor = end + 1
        index = end + 1

    if cursor < len(lines):
        tail = "".join(lines[cursor:])
        text_chunks, chunk_index = chunk_text_regions(
            content=tail,
            path=path,
            root=root,
            chunk_index_start=chunk_index,
            language=language,
        )
        chunks.extend(text_chunks)

    return chunks


def chunk_markup_file(path: Path, root: Path, content: str, language: str) -> list[CodeChunk]:
    if language == "markdown":
        sections: list[str] = []
        current: list[str] = []
        for line in content.splitlines(keepends=True):
            if line.startswith("#") and current:
                sections.append("".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("".join(current))

        chunks: list[CodeChunk] = []
        chunk_index = 0
        for section in sections:
            for part, start, end in split_large_text(section):
                chunks.append(
                    make_chunk(
                        content=part,
                        path=path,
                        root=root,
                        chunk_index=chunk_index,
                        language=language,
                        start_line=start,
                        end_line=end,
                    )
                )
                chunk_index += 1
        return chunks

    chunks, _ = chunk_text_regions(
        content=content,
        path=path,
        root=root,
        chunk_index_start=0,
        language=language,
    )
    return chunks


def chunk_file(path: Path, root: Path) -> list[CodeChunk]:
    content = read_text(path)
    if not content.strip():
        return []
    language = infer_language(path)
    if language == "python":
        return chunk_python_file(path, root, content)
    if language in {"javascript", "typescript", "tsx"}:
        return chunk_javascript_like_file(path, root, content, language)
    return chunk_markup_file(path, root, content, language)


def scan_codebase(root: Path) -> tuple[int, list[CodeChunk]]:
    files = iter_source_files(root)
    chunks: list[CodeChunk] = []
    for file_index, path in enumerate(files, start=1):
        try:
            file_chunks = chunk_file(path, root)
        except Exception as exc:
            LOGGER.warning("Failed to chunk %s: %s", path, exc)
            continue
        chunks.extend(file_chunks)
        if file_index % 25 == 0 or file_index == len(files):
            LOGGER.info("Scanned %s/%s files, %s chunks", file_index, len(files), len(chunks))
    return len(files), chunks


def batches(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def response_data(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    if data is None:
        return []
    return data


def fetch_existing_hashes(supabase: Any, hashes: list[str]) -> set[str]:
    existing: set[str] = set()
    for hash_batch in batches(hashes, 100):
        if not hash_batch:
            continue
        response = (
            supabase.table("code_chunks")
            .select("content_hash")
            .in_("content_hash", hash_batch)
            .eq("model_name", MODEL_NAME)
            .execute()
        )
        existing.update(row["content_hash"] for row in response_data(response) if row.get("content_hash"))
    return existing


def fetch_indexed_file_state(supabase: Any) -> dict[str, set[str]]:
    state: dict[str, set[str]] = {}
    page_size = 1000
    offset = 0

    while True:
        response = (
            supabase.table("code_chunks")
            .select("content_hash,metadata")
            .contains("metadata", {"project": PROJECT_NAME})
            .eq("model_name", MODEL_NAME)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = response_data(response)
        if not rows:
            break

        for row in rows:
            metadata = row.get("metadata") or {}
            file_path = metadata.get("file_path")
            content_hash_value = row.get("content_hash")
            if file_path and content_hash_value:
                state.setdefault(file_path, set()).add(content_hash_value)

        if len(rows) < page_size:
            break
        offset += page_size

    return state


def fetch_active_embedding_dimension(supabase: Any) -> int | None:
    response = (
        supabase.table("code_chunks")
        .select("embedding_dimension")
        .eq("model_name", MODEL_NAME)
        .limit(1)
        .execute()
    )
    rows = response_data(response)
    if not rows:
        return None
    dimension = rows[0].get("embedding_dimension")
    return int(dimension) if dimension else None


def delete_chunks_for_paths(supabase: Any, file_paths: list[str]) -> int:
    deleted_rows = 0
    for file_path in sorted(set(file_paths)):
        response = (
            supabase.table("code_chunks")
            .delete()
            .eq("model_name", MODEL_NAME)
            .contains("metadata", {"project": PROJECT_NAME, "file_path": file_path})
            .execute()
        )
        deleted_rows += len(response_data(response))
    return deleted_rows


def insert_rows_with_retry(
    supabase: Any,
    rows: list[dict[str, Any]],
    *,
    retries: int = 3,
    delay_seconds: float = 1.0,
) -> None:
    attempt = 0
    while True:
        try:
            supabase.table("code_chunks").insert(rows).execute()
            return
        except Exception:
            attempt += 1
            if attempt > retries:
                raise
            sleep_for = delay_seconds * (2 ** (attempt - 1))
            LOGGER.warning("Insert failed; retrying in %.1fs (%s/%s)", sleep_for, attempt, retries)
            time.sleep(sleep_for)


def count_code_rows(supabase: Any, project: str = PROJECT_NAME) -> int | None:
    try:
        response = (
            supabase.table("code_chunks")
            .select("id", count="exact")
            .contains("metadata", {"project": project})
            .eq("model_name", MODEL_NAME)
            .limit(1)
            .execute()
        )
        return getattr(response, "count", None)
    except Exception:
        response = supabase.table("code_chunks").select("id", count="exact").limit(1).execute()
        return getattr(response, "count", None)


def embedding_sample_exists(supabase: Any, project: str = PROJECT_NAME) -> bool:
    try:
        response = (
            supabase.table("code_chunks")
            .select("embedding")
            .contains("metadata", {"project": project})
            .eq("model_name", MODEL_NAME)
            .limit(1)
            .execute()
        )
        rows = response_data(response)
        return bool(rows and rows[0].get("embedding") is not None)
    except Exception:
        return False


def create_index_run(supabase: Any, embedding_dimension: int) -> int | None:
    try:
        response = (
            supabase.table("code_index_runs")
            .insert(
                {
                    "project": PROJECT_NAME,
                    "model_name": MODEL_NAME,
                    "model_revision": MODEL_REVISION,
                    "embedding_dimension": embedding_dimension,
                    "status": "running",
                }
            )
            .execute()
        )
        rows = response_data(response)
        if rows:
            return rows[0].get("id")
    except Exception as exc:
        LOGGER.warning("Could not create code_index_runs record: %s", exc)
    return None


def finish_index_run(
    supabase: Any,
    run_id: int | None,
    *,
    status: str,
    files_processed: int = 0,
    chunks_created: int = 0,
    rows_inserted: int = 0,
    rows_skipped: int = 0,
    db_rows: int | None = None,
    error: str | None = None,
) -> None:
    if run_id is None:
        return
    payload = {
        "status": status,
        "files_processed": files_processed,
        "chunks_created": chunks_created,
        "rows_inserted": rows_inserted,
        "rows_skipped": rows_skipped,
        "db_rows": db_rows,
        "error": error,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    try:
        supabase.table("code_index_runs").update(payload).eq("id", run_id).execute()
    except Exception as exc:
        LOGGER.warning("Could not update code_index_runs record %s: %s", run_id, exc)


def normalize_snippet(content: str, max_chars: int = 1200) -> str:
    snippet = content.strip()
    if len(snippet) <= max_chars:
        return snippet
    return snippet[:max_chars].rstrip() + "\n..."


def safe_file_path(root: Path, requested_path: str) -> Path:
    candidate = Path(requested_path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root / requested_path).resolve()
    if root.resolve() not in [resolved, *resolved.parents]:
        raise ValueError("Requested path is outside the indexed codebase.")
    if not resolved.is_file():
        raise FileNotFoundError(requested_path)
    return resolved


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codebase", help="Path to the umre_ops codebase. Defaults to CODEBASE_ROOT or inferred repo root.")
    parser.add_argument(
        "--model",
        default=MODEL_NAME,
        help=f"Embedding model. Defaults to CODE_INTEL_MODEL_NAME or {DEFAULT_MODEL_NAME}.",
    )
    parser.add_argument(
        "--model-revision",
        default=MODEL_REVISION,
        help="Optional Hugging Face model revision. Defaults to CODE_INTEL_MODEL_REVISION.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
