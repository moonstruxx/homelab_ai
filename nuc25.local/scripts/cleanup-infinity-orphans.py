#!/usr/bin/env python3
"""Find (and optionally delete) Infinity data no longer referenced by MySQL.

Two kinds of orphans:
  - whole tables ragflow_<tenant_id>_<kb_id> where kb_id no longer exists in `knowledgebase`
    (the whole dataset was deleted from RAGFlow but its Infinity table was left behind)
  - individual doc_id chunks left behind inside a live KB's table after the document
    row was deleted from `document` (e.g. a failed/partial delete)

Dry run by default; pass --apply to actually delete.

Must run inside the ragflow container (needs the app's DB/Infinity connection settings):
  docker cp scripts/cleanup-infinity-orphans.py rag_ai_stack-ragflow-1:/tmp/
  docker exec -i rag_ai_stack-ragflow-1 python3 /tmp/cleanup-infinity-orphans.py
  docker exec -i rag_ai_stack-ragflow-1 python3 /tmp/cleanup-infinity-orphans.py --apply
"""
import argparse
import logging
import re

logging.basicConfig(level=logging.INFO)

from common import settings
settings.init_settings()
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.document_service import DocumentService

TABLE_RE = re.compile(r"^ragflow_([0-9a-f]{32})_([0-9a-f]{32})$")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Delete orphans (default: report only)")
    args = parser.parse_args()

    kbs = {kb.id: kb.tenant_id for kb in KnowledgebaseService.model.select(KnowledgebaseService.model.id, KnowledgebaseService.model.tenant_id)}
    print(f"Live knowledgebases: {len(kbs)}")

    doc_store = settings.docStoreConn
    inf_conn = doc_store.connPool.get_conn()
    try:
        table_names = inf_conn.get_database(doc_store.dbName).list_tables().table_names
    finally:
        doc_store.connPool.release_conn(inf_conn)

    orphan_tables = []
    kb_tables = []
    for t in table_names:
        m = TABLE_RE.match(t)
        if not m:
            continue  # infra tables: ragflow_doc_meta_<tenant>, ragflow_<tenant>_none
        tenant_id, kb_id = m.groups()
        (orphan_tables if kb_id not in kbs else kb_tables).append((t, tenant_id, kb_id))

    print("\n=== Orphaned tables (KB deleted from MySQL) ===")
    for t, tenant_id, kb_id in orphan_tables:
        print(f"  {t}  (kb_id={kb_id} not in knowledgebase table)")
    if not orphan_tables:
        print("  none")

    print("\n=== Orphaned chunks within live KB tables ===")
    total_orphan_chunks = 0
    for t, tenant_id, kb_id in kb_tables:
        valid_doc_ids = {d.id for d in DocumentService.model.select(DocumentService.model.id).where(DocumentService.model.kb_id == kb_id)}

        inf_conn = doc_store.connPool.get_conn()
        try:
            table_instance = inf_conn.get_database(doc_store.dbName).get_table(t)
            df, _ = table_instance.output(["doc_id"]).limit(1000000).to_df()
        finally:
            doc_store.connPool.release_conn(inf_conn)

        infinity_doc_ids = set(df["doc_id"].tolist()) if df is not None and not df.empty else set()
        orphan_doc_ids = infinity_doc_ids - valid_doc_ids

        if orphan_doc_ids:
            chunk_count = int(df["doc_id"].isin(orphan_doc_ids).sum())
            total_orphan_chunks += chunk_count
            print(f"  {t}: {len(orphan_doc_ids)} orphaned doc_id(s), {chunk_count} chunk(s)")
            if args.apply:
                index_name = f"ragflow_{tenant_id}"
                deleted = doc_store.delete({"doc_id": list(orphan_doc_ids)}, index_name, kb_id)
                print(f"    deleted {deleted} chunks")
        else:
            print(f"  {t}: clean ({len(infinity_doc_ids)} doc_id(s), all referenced)")

    if args.apply:
        for t, tenant_id, kb_id in orphan_tables:
            index_name = f"ragflow_{tenant_id}"
            doc_store.delete_idx(index_name, kb_id)
            print(f"Dropped orphaned table {t}")
    elif orphan_tables or total_orphan_chunks:
        print("\nDry run only. Re-run with --apply to delete the above.")
    else:
        print("\nNothing to clean up.")


if __name__ == "__main__":
    main()
