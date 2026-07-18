#!/usr/bin/env python3
"""Clean up laws_fine_chuncked after concurrent re-parse attempts left duplicate/stale
chunks in Infinity, then reset MySQL state for all 6 documents ready for a strictly
serial re-parse (one document at a time -- see driver script/loop, not done here).

Bug found 2026-07-17: multiple documents in this KB were re-queued around the same
time and ended up processing concurrently across the task executor's 2 worker
processes. At least one document (GG.pdf) got through parsing/chunking/embedding
successfully every time but then silently failed at the final indexing step
(chunk_num never incremented) across 4 consecutive retries, correlated with
repeated `RuntimeError: Attempted to exit cancel scope in a different task than it
was entered in` (anyio/httpcore) during the same window -- consistent with a
concurrency bug when multiple documents' async tasks share HTTP client/connection
pool state inside one task-executor worker process. Critically, the insert path
does NOT delete a document's prior Infinity chunks before a retry re-inserts new
ones -- confirmed via live inspection (GG.pdf's row count climbed from a 179-row
baseline to 243 after 4 failed/retried attempts, all while document.chunk_num
stayed 0), so repeated retries silently accumulate duplicate/stale rows rather
than replacing them.

This deletes each document's existing rows individually by doc_id (scoped, not a
full table/index drop) before resetting MySQL state, so a subsequent serial
re-parse starts from zero rows per document.

    docker cp scripts/wipe-and-serial-requeue-laws-kb-20260717.py rag_ai_stack-ragflow-1:/tmp/
    docker exec -i rag_ai_stack-ragflow-1 python3 /tmp/wipe-and-serial-requeue-laws-kb-20260717.py
"""
from common import settings

settings.init_settings()
from api.db.services.document_service import DocumentService
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.task_service import TaskService, cancel_all_task_of

KB_ID = "65d9f3367cd111f19b6e25d679132943"


def main():
    kb = KnowledgebaseService.query(id=KB_ID)[0]
    tenant_id = kb.tenant_id
    docs = list(DocumentService.model.select().where(DocumentService.model.kb_id == KB_ID))
    assert len(docs) == 6, f"expected 6 docs, found {len(docs)} -- abort"

    doc_store = settings.docStoreConn
    idx_nm = f"ragflow_{tenant_id}"
    table_name = f"{idx_nm}_{KB_ID}"

    def row_count(doc_id):
        conn = doc_store.connPool.get_conn()
        try:
            table = conn.get_database(doc_store.dbName).get_table(table_name)
            df, _ = table.output(["id", "doc_id"]).to_df()
            return int((df["doc_id"] == doc_id).sum())
        except Exception as e:
            return f"<table lookup failed: {e}>"
        finally:
            doc_store.connPool.release_conn(conn)

    print(f"KB {KB_ID} ({kb.name!r}), tenant {tenant_id}: cancelling + clearing state for {len(docs)} docs")
    for doc in docs:
        cancel_all_task_of(doc.id)
        TaskService.model.delete().where(TaskService.model.doc_id == doc.id).execute()
        DocumentService.model.update(chunk_num=0, progress=0, progress_msg="").where(
            DocumentService.model.id == doc.id
        ).execute()

        before_count = row_count(doc.id)
        deleted = doc_store.delete({"doc_id": doc.id}, idx_nm, KB_ID)
        after_count = row_count(doc.id)
        print(f"  {doc.name}: deleted={deleted} (before={before_count}, after={after_count})")

    KnowledgebaseService.model.update(chunk_num=0).where(KnowledgebaseService.model.id == KB_ID).execute()
    print("Reset knowledgebase.chunk_num to 0. doc_num left untouched (already correct at 6).")
    print("Done. Documents are reset and ready to be re-queued ONE AT A TIME by the driver loop.")


if __name__ == "__main__":
    main()
