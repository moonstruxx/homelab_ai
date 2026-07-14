#!/usr/bin/env python3
"""Clean up stuck task and re-queue BIA/disting/H9."""
import logging

logging.basicConfig(level=logging.INFO)

from common import settings
settings.init_settings()
from api.db.services.document_service import DocumentService
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.task_service import TaskService

KB_ID = "671bd9ac74d511f19603fdb0dbbcdc6c"
DOC_IDS = [
    "f5636cf274e411f1a3dd87e954d01313",  # BIA patchbook.cdr - noiseeng.pdf
    "f8703a8874e411f1a3dd87e954d01313",  # disting_NT_lua_scripting_1.16_26.docx
    "f891177674e411f1a3dd87e954d01313",  # H9-UserGuide.pdf
]
STUCK_TASK = "b4c0a04a750f11f1a6245f9fb4d6d130"  # 2C53P pages 72-76


def main():
    # Mark stuck 2C53P task done
    TaskService.update_by_id(STUCK_TASK, {"progress": 1.0, "progress_msg": "\nSkipped stuck VLM step."})
    print(f"Marked stuck task {STUCK_TASK} as done")

    kb = KnowledgebaseService.query(id=KB_ID)[0]
    tenant_id = kb.tenant_id

    # Delete existing tasks and clear chunk_num for docs to re-queue
    for doc_id in DOC_IDS:
        doc = DocumentService.query(id=doc_id)[0].to_dict()
        print(f"Resetting {doc['name']} ({doc_id})")
        TaskService.model.delete().where(TaskService.model.doc_id == doc_id).execute()
        DocumentService.clear_chunk_num(doc_id)

    # Re-queue
    kb_table_num_map = {}
    for doc_id in DOC_IDS:
        doc = DocumentService.query(id=doc_id)[0].to_dict()
        print(f"Re-parsing {doc['name']} ({doc_id})")
        DocumentService.run(tenant_id, doc, kb_table_num_map)
        print(f"  -> queued")

    print("Done.")


if __name__ == "__main__":
    main()
