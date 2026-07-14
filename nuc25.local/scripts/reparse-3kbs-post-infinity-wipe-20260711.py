#!/usr/bin/env python3
"""Reset and re-queue all documents in droid/switch/laws_fine_chuncked after the
2026-07-11 full Infinity data-dir wipe (see CLAUDE.md). MySQL's document rows still
describe chunk/progress state that no longer exists in Infinity; this clears that
stale state and re-queues every document in the three affected KBs for re-parsing.
"""
import logging

logging.basicConfig(level=logging.INFO)

from common import settings
settings.init_settings()
from api.db.services.document_service import DocumentService
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.task_service import cancel_all_task_of, TaskService

KB_IDS = [
    "5b7db90273be11f1973ea923a4b850bd",  # droid
    "671bd9ac74d511f19603fdb0dbbcdc6c",  # switch
    "65d9f3367cd111f19b6e25d679132943",  # laws_fine_chuncked
]


def main():
    from rag.utils.redis_conn import REDIS_CONN
    from common import settings as common_settings

    all_doc_ids = []
    kb_tenant = {}
    for kb_id in KB_IDS:
        kb = KnowledgebaseService.query(id=kb_id)[0]
        kb_tenant[kb_id] = kb.tenant_id
        doc_ids = [d.id for d in DocumentService.model.select(DocumentService.model.id).where(DocumentService.model.kb_id == kb_id)]
        print(f"KB {kb_id} ({kb.name}): {len(doc_ids)} documents, tenant {kb.tenant_id}")
        all_doc_ids.extend(doc_ids)

    print(f"Total documents to reset+requeue: {len(all_doc_ids)}")

    print("Cancelling and deleting all existing tasks for these documents...")
    for doc_id in all_doc_ids:
        cancel_all_task_of(doc_id)
    TaskService.model.delete().where(TaskService.model.doc_id.in_(all_doc_ids)).execute()

    for kb_id in KB_IDS:
        DocumentService.model.update(chunk_num=0, progress=0, progress_msg="").where(DocumentService.model.kb_id == kb_id).execute()

    print("Clearing Redis task stream...")
    stream = common_settings.get_svr_queue_name(0, "common")
    REDIS_CONN.REDIS.delete(stream)
    print(f"  deleted {stream}")

    print("Re-queuing all documents...")
    kb_table_num_map = {}
    for kb_id in KB_IDS:
        tenant_id = kb_tenant[kb_id]
        doc_ids = [d.id for d in DocumentService.model.select(DocumentService.model.id).where(DocumentService.model.kb_id == kb_id)]
        for doc_id in doc_ids:
            doc = DocumentService.query(id=doc_id)[0].to_dict()
            DocumentService.clear_chunk_num(doc_id)
            DocumentService.run(tenant_id, doc, kb_table_num_map)
        print(f"  KB {kb_id}: queued {len(doc_ids)} documents")

    print(f"Done. Queued {len(all_doc_ids)} documents total. Monitor via document.chunk_num / progress.")


if __name__ == "__main__":
    main()
