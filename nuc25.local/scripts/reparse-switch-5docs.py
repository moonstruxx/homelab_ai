#!/usr/bin/env python3
"""Clear switch dataset tasks and re-queue only selected 5 docs with hybrid-engine."""
import logging

logging.basicConfig(level=logging.INFO)

from common import settings
settings.init_settings()
from api.db.services.document_service import DocumentService
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.task_service import cancel_all_task_of
from api.db.services.task_service import queue_tasks
from peewee import Model

KB_ID = "671bd9ac74d511f19603fdb0dbbcdc6c"
DOC_IDS = [
    "f543658874e411f1a3dd87e954d01313",  # 2C53P-_Manual.pdf
    "f5636cf274e411f1a3dd87e954d01313",  # BIA patchbook.cdr - noiseeng.pdf
    "f8703a8874e411f1a3dd87e954d01313",  # disting_NT_lua_scripting_1.16_26.docx
    "f891177674e411f1a3dd87e954d01313",  # H9-UserGuide.pdf
    "f89e40ae74e411f1a3dd87e954d01313",  # Hydronium-User-Guide-v1.02.pdf
]


def main():
    kb = KnowledgebaseService.query(id=KB_ID)[0]
    tenant_id = kb.tenant_id
    print(f"KB: {KB_ID}, tenant: {tenant_id}")

    # Cancel and delete tasks for ALL docs in the KB to clear the pipeline
    print("Cancelling all tasks in switch dataset...")
    from api.db.services.task_service import TaskService
    all_doc_ids = [d.id for d in DocumentService.model.select(DocumentService.model.id).where(DocumentService.model.kb_id == KB_ID)]
    for doc_id in all_doc_ids:
        cancel_all_task_of(doc_id)
    TaskService.model.delete().where(TaskService.model.doc_id.in_(all_doc_ids)).execute()
    DocumentService.model.update(chunk_num=0).where(DocumentService.model.kb_id == KB_ID).execute()
    print(f"  cleared {len(all_doc_ids)} documents")

    # Clear Redis stream (delete all pending tasks)
    print("Clearing Redis task stream...")
    from rag.utils.redis_conn import REDIS_CONN
    from common import settings as common_settings
    stream = common_settings.get_svr_queue_name(0, "common")
    REDIS_CONN.REDIS.delete(stream)
    print(f"  deleted {stream}")

    # Re-queue selected 5 docs
    kb_table_num_map = {}
    for doc_id in DOC_IDS:
        doc = DocumentService.query(id=doc_id)[0].to_dict()
        print(f"Re-parsing {doc['name']} ({doc_id})")
        # Reset chunk num
        DocumentService.clear_chunk_num(doc_id)
        DocumentService.run(tenant_id, doc, kb_table_num_map)
        print(f"  -> queued")

    print("Done. Monitor via document.chunk_num.")


if __name__ == "__main__":
    main()
