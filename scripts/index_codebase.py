from dotenv import load_dotenv
import os

load_dotenv()

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.code_intel_common import (
        DEFAULT_EMBEDDING_DIMENSION,
        DEFAULT_MATCH_COUNT,
        LOGGER,
        add_common_arguments,
        active_model_name,
        active_model_revision,
        batches,
        configure_logging,
        count_code_rows,
        create_index_run,
        delete_chunks_for_paths,
        detect_embedding_dimension,
        encode_query,
        encode_texts,
        embedding_sample_exists,
        fetch_existing_hashes,
        fetch_indexed_file_state,
        finish_index_run,
        get_embedding_model,
        get_supabase_client,
        initialize_database_schema,
        insert_rows_with_retry,
        iter_source_files,
        json_dumps,
        reset_schema_sql,
        resolve_codebase_root,
        scan_codebase,
        schema_sql,
        set_model_config,
    )
except ModuleNotFoundError:
    from code_intel_common import (
        DEFAULT_EMBEDDING_DIMENSION,
        DEFAULT_MATCH_COUNT,
        LOGGER,
        add_common_arguments,
        active_model_name,
        active_model_revision,
        batches,
        configure_logging,
        count_code_rows,
        create_index_run,
        delete_chunks_for_paths,
        detect_embedding_dimension,
        encode_query,
        encode_texts,
        embedding_sample_exists,
        fetch_existing_hashes,
        fetch_indexed_file_state,
        finish_index_run,
        get_embedding_model,
        get_supabase_client,
        initialize_database_schema,
        insert_rows_with_retry,
        iter_source_files,
        json_dumps,
        reset_schema_sql,
        resolve_codebase_root,
        scan_codebase,
        schema_sql,
        set_model_config,
    )


def index_codebase(
    *,
    codebase_root: Path,
    batch_size: int,
    embedding_batch_size: int,
    init_db: bool,
    print_sql: bool,
    incremental: bool,
    test_query: str | None,
) -> dict[str, Any]:
    LOGGER.info("Loading embedding model: %s", active_model_name())
    model = get_embedding_model()
    embedding_dimension = detect_embedding_dimension(model)
    LOGGER.info("Embedding dimension detected: %s", embedding_dimension)

    if print_sql:
        print(schema_sql(embedding_dimension))

    if init_db:
        LOGGER.info("Initializing Supabase pgvector schema")
        initialize_database_schema(embedding_dimension)

    supabase = get_supabase_client()
    run_id = create_index_run(supabase, embedding_dimension)

    try:
        LOGGER.info("Scanning codebase: %s", codebase_root)
        current_file_paths = {str(path.relative_to(codebase_root)) for path in iter_source_files(codebase_root)}
        files_processed, chunks = scan_codebase(codebase_root)
        LOGGER.info("Scan complete: %s files processed, %s chunks produced", files_processed, len(chunks))

        seen_hashes: set[str] = set()
        unique_chunks = []
        for chunk in chunks:
            if chunk.content_hash in seen_hashes:
                continue
            seen_hashes.add(chunk.content_hash)
            unique_chunks.append(chunk)

        duplicate_in_scan = len(chunks) - len(unique_chunks)
        if duplicate_in_scan:
            LOGGER.info("Skipped %s duplicate chunks within this scan", duplicate_in_scan)

        deleted_rows = 0
        unchanged_files = 0
        changed_files = 0
        stale_files = 0
        if incremental:
            chunks_by_file: dict[str, list[Any]] = {}
            for chunk in unique_chunks:
                chunks_by_file.setdefault(chunk.metadata["file_path"], []).append(chunk)

            indexed_state = fetch_indexed_file_state(supabase)
            stale_paths = sorted(set(indexed_state) - current_file_paths)
            changed_paths: list[str] = []
            chunks_to_consider = []

            for file_path in sorted(current_file_paths):
                current_chunks = chunks_by_file.get(file_path, [])
                current_hashes = {chunk.content_hash for chunk in current_chunks}
                indexed_hashes = indexed_state.get(file_path)
                if indexed_hashes is not None and indexed_hashes == current_hashes:
                    unchanged_files += 1
                    continue
                if indexed_hashes is not None:
                    changed_paths.append(file_path)
                    changed_files += 1
                chunks_to_consider.extend(current_chunks)

            delete_paths = stale_paths + changed_paths
            stale_files = len(stale_paths)
            if delete_paths:
                deleted_rows = delete_chunks_for_paths(supabase, delete_paths)
                LOGGER.info(
                    "Incremental cleanup: %s stale files, %s changed files, %s rows deleted",
                    stale_files,
                    changed_files,
                    deleted_rows,
                )
            LOGGER.info(
                "Incremental plan: %s unchanged files, %s files needing indexing",
                unchanged_files,
                len(current_file_paths) - unchanged_files,
            )
        else:
            chunks_to_consider = unique_chunks

        skipped_existing = 0
        chunks_to_index = []
        for chunk_batch in batches(chunks_to_consider, batch_size):
            existing_hashes = fetch_existing_hashes(supabase, [chunk.content_hash for chunk in chunk_batch])
            new_chunks = [chunk for chunk in chunk_batch if chunk.content_hash not in existing_hashes]
            skipped_existing += len(chunk_batch) - len(new_chunks)
            chunks_to_index.extend(new_chunks)

        inserted_rows = 0
        total_to_insert = len(chunks_to_index)
        LOGGER.info(
            "Index plan: %s candidate chunks, %s already indexed, %s to insert",
            len(chunks_to_consider),
            skipped_existing,
            total_to_insert,
        )

        for embed_batch in batches(chunks_to_index, embedding_batch_size):
            embeddings = encode_texts(model, [chunk.content for chunk in embed_batch], batch_size=embedding_batch_size)
            rows = [
                {
                    "content": chunk.content,
                    "embedding": embedding,
                    "metadata": {
                        **chunk.metadata,
                        "model_name": active_model_name(),
                        "model_revision": active_model_revision(),
                        "embedding_dimension": embedding_dimension,
                    },
                    "content_hash": chunk.content_hash,
                    "model_name": active_model_name(),
                    "model_revision": active_model_revision(),
                    "embedding_dimension": embedding_dimension,
                }
                for chunk, embedding in zip(embed_batch, embeddings, strict=True)
            ]
            insert_rows_with_retry(supabase, rows)
            inserted_rows += len(rows)
            percent = (inserted_rows / total_to_insert * 100) if total_to_insert else 100
            LOGGER.info(
                "Inserted %s rows (%s/%s, %.1f%%)",
                len(rows),
                inserted_rows,
                total_to_insert,
                percent,
            )

        db_rows = count_code_rows(supabase)
    except Exception as exc:
        finish_index_run(
            supabase,
            run_id,
            status="failed",
            files_processed=locals().get("files_processed", 0),
            chunks_created=len(locals().get("chunks", [])),
            rows_inserted=locals().get("inserted_rows", 0),
            rows_skipped=locals().get("skipped_existing", 0),
            error=str(exc),
        )
        raise

    finish_index_run(
        supabase,
        run_id,
        status="completed",
        files_processed=files_processed,
        chunks_created=len(chunks),
        rows_inserted=inserted_rows,
        rows_skipped=skipped_existing,
        db_rows=db_rows,
    )
    LOGGER.info("Indexing complete: %s rows inserted, %s DB rows for active model", inserted_rows, db_rows)
    validation: dict[str, Any] = {
        "files_processed": files_processed,
        "chunks": len(chunks),
        "unique_chunks": len(unique_chunks),
        "inserted_rows": inserted_rows,
        "skipped_existing_rows": skipped_existing,
        "deleted_rows": deleted_rows,
        "unchanged_files": unchanged_files,
        "changed_files": changed_files,
        "stale_files": stale_files,
        "db_rows": db_rows,
        "embedding_sample_present": embedding_sample_exists(supabase),
        "model_name": active_model_name(),
        "model_revision": active_model_revision(),
        "embedding_dimension": embedding_dimension,
    }

    if test_query:
        LOGGER.info("Running validation search: %s", test_query)
        query_embedding = encode_query(model, test_query)
        response = supabase.rpc(
            "match_code_chunks",
            {
                "query_embedding": query_embedding,
                "match_count": DEFAULT_MATCH_COUNT,
                "query_model_name": active_model_name(),
            },
        ).execute()
        validation["test_query"] = test_query
        validation["test_results"] = [
            {
                "file_path": row.get("metadata", {}).get("file_path"),
                "score": row.get("similarity"),
                "snippet": row.get("content", "")[:300],
            }
            for row in (getattr(response, "data", None) or [])
        ]

    return validation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Index the umre_ops codebase into Supabase pgvector.")
    add_common_arguments(parser)
    parser.add_argument("--batch-size", type=int, default=100, help="Chunk batch size for deduplication.")
    parser.add_argument("--embedding-batch-size", type=int, default=16, help="Embedding model batch size.")
    parser.add_argument("--init-db", action="store_true", help="Create pgvector table, index, and match function.")
    parser.add_argument(
        "--no-incremental",
        action="store_true",
        help="Disable changed/deleted file cleanup and keep append-only hash deduplication behavior.",
    )
    parser.add_argument("--print-sql", action="store_true", help="Print the schema SQL for Supabase SQL Editor.")
    parser.add_argument(
        "--print-reset-sql",
        action="store_true",
        help="Print destructive SQL to drop the old code_chunks table/function before model migration.",
    )
    parser.add_argument(
        "--detect-dimension",
        action="store_true",
        help="Load the embedding model to detect dimension before printing SQL.",
    )
    parser.add_argument(
        "--test-query",
        default="dashboard logic",
        help="Validation query to run after indexing. Use an empty string to disable.",
    )
    parser.add_argument(
        "--schema-dimension",
        type=int,
        default=DEFAULT_EMBEDDING_DIMENSION,
        help="Dimension used only for --print-sql before the model is loaded.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)
    set_model_config(args.model, args.model_revision)

    if args.print_reset_sql:
        print(reset_schema_sql())
        return 0

    if args.print_sql and not args.init_db:
        dimension = args.schema_dimension
        if args.detect_dimension:
            dimension = detect_embedding_dimension(get_embedding_model())
        print(schema_sql(dimension, active_model_name()))
        return 0

    try:
        codebase_root = resolve_codebase_root(args.codebase)
        validation = index_codebase(
            codebase_root=codebase_root,
            batch_size=args.batch_size,
            embedding_batch_size=args.embedding_batch_size,
            init_db=args.init_db,
            print_sql=args.print_sql,
            incremental=not args.no_incremental,
            test_query=args.test_query or None,
        )
    except Exception as exc:
        LOGGER.exception("Indexing failed: %s", exc)
        return 1

    print(json_dumps(validation))
    return 0


if __name__ == "__main__":
    sys.exit(main())
