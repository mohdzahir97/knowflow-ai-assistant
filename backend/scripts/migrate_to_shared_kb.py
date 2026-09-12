"""One-off migration: per-user Chroma collections -> one shared knowledge base.

Background
----------
The knowledge base used to be private to each uploader, so vectors lived in
collections keyed by `sha1(user_id:provider:model)`. It is now a single
shared corpus curated by admins, keyed by `sha1(provider:model)` alone.
Existing vectors therefore sit in collections nothing reads any more.

This copies them across *without re-embedding*: the stored vectors are read
out and written straight into the destination, so no provider API calls are
made and no cost is incurred. Re-uploading the source PDFs would be the
alternative and is far slower.

Safety
------
- Idempotent: chunks already present in the destination are skipped, so
  re-running cannot duplicate content.
- Non-destructive: source collections are left untouched. Verify the result,
  then delete them with --delete-source if you want the space back.
- Dry run by default; pass --apply to actually write.

Usage
-----
    python scripts/migrate_to_shared_kb.py            # report only
    python scripts/migrate_to_shared_kb.py --apply
    python scripts/migrate_to_shared_kb.py --apply --delete-source
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a plain script from the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.vector_store_service import VectorStoreService  # noqa: E402

# Legacy per-user collections used this prefix; shared ones use "kb_shared_".
_LEGACY_PREFIX = "kb_"
_SHARED_PREFIX = "kb_shared_"
_COPY_BATCH = 200


def _legacy_collections(client) -> list:
    return [
        c
        for c in client.list_collections()
        if c.name.startswith(_LEGACY_PREFIX) and not c.name.startswith(_SHARED_PREFIX)
    ]


def _document_embedding_configs() -> dict:
    """Map document_id -> (provider, model) from the SQL system of record.

    The collection name is a hash, so the embedding configuration cannot be
    recovered from it. The documents table is the only place that records
    which configuration each chunk was produced with.
    """
    from app.db.models.document import Document
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return {
            doc.id: (doc.embedding_provider, doc.embedding_model)
            for doc in db.query(Document).all()
            if doc.embedding_provider and doc.embedding_model
        }


def migrate(apply_changes: bool, delete_source: bool) -> int:
    settings = get_settings()
    client = chromadb.PersistentClient(path=str(settings.chroma_path))
    service = VectorStoreService()

    legacy = _legacy_collections(client)
    if not legacy:
        print("No legacy per-user collections found - nothing to migrate.")
        return 0

    configs = _document_embedding_configs()
    if not configs:
        print("No documents in the database; cannot determine embedding configs. Aborting.")
        return 1

    total_copied = 0
    for collection_info in legacy:
        source = client.get_collection(collection_info.name)
        record = source.get(include=["embeddings", "documents", "metadatas"])
        ids = record.get("ids") or []
        if not ids:
            print(f"  {collection_info.name}: empty, skipping")
            continue

        # Group chunks by the embedding config of their parent document, since
        # one legacy collection only ever held a single config in practice but
        # we should not assume it.
        grouped: dict = {}
        for index, chunk_id in enumerate(ids):
            metadata = record["metadatas"][index] or {}
            config = configs.get(metadata.get("document_id"))
            if config is None:
                continue
            grouped.setdefault(config, []).append(index)

        for (provider, model), indices in grouped.items():
            destination_name = service.collection_name(provider, model)
            destination = client.get_or_create_collection(destination_name)
            existing = set(destination.get(include=[]).get("ids") or [])

            pending = [i for i in indices if ids[i] not in existing]
            skipped = len(indices) - len(pending)
            print(
                f"  {collection_info.name} -> {destination_name} "
                f"[{provider}/{model}]: {len(pending)} to copy, {skipped} already present"
            )

            if not apply_changes or not pending:
                total_copied += len(pending)
                continue

            for start in range(0, len(pending), _COPY_BATCH):
                batch = pending[start : start + _COPY_BATCH]
                destination.add(
                    ids=[ids[i] for i in batch],
                    embeddings=[record["embeddings"][i] for i in batch],
                    documents=[record["documents"][i] for i in batch],
                    metadatas=[record["metadatas"][i] for i in batch],
                )
            total_copied += len(pending)

        if apply_changes and delete_source:
            client.delete_collection(collection_info.name)
            print(f"  deleted source collection {collection_info.name}")

    if apply_changes:
        print(f"\nMigrated {total_copied} chunks into the shared knowledge base.")
    else:
        print(f"\nDRY RUN - would migrate {total_copied} chunks. Re-run with --apply to perform it.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="perform the migration (default is a dry run)")
    parser.add_argument("--delete-source", action="store_true", help="remove legacy collections after copying")
    args = parser.parse_args()
    raise SystemExit(migrate(apply_changes=args.apply, delete_source=args.delete_source))
