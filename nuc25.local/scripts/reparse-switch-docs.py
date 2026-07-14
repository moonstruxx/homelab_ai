#!/usr/bin/env python3
"""Cancel and re-queue parsing for selected documents with current MinerU config."""
import logging

logging.basicConfig(level=logging.INFO)

from common import settings
settings.init_settings()
from api.db.services.document_service import DocumentService
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.task_service import cancel_all_task_of

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

    for doc_id in DOC_IDS:
        doc = DocumentService.query(id=doc_id)[0].to_dict()
        print(f"Cancelling tasks for {doc['name']} ({doc_id})")
        cancel_all_task_of(doc_id)

    kb_table_num_map = {}
    for doc_id in DOC_IDS:
        doc = DocumentService.query(id=doc_id)[0].to_dict()
        print(f"Re-parsing {doc['name']} ({doc_id}) parser={doc.get('parser_id')} mineru_backend will be read from model config")
        DocumentService.run(tenant_id, doc, kb_table_num_map)
        print(f"  -> queued")

    print("Done.")


if __name__ == "__main__":
    main()
