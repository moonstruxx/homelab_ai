#!/usr/bin/env python3
from common import settings
settings.init_settings()
from api.db.services.document_service import DocumentService
from api.db.services.knowledgebase_service import KnowledgebaseService

KB_ID = "65d9f3367cd111f19b6e25d679132943"

docs = DocumentService.model.select().where(DocumentService.model.kb_id == KB_ID)
print(f"Resetting {docs.count()} documents...")
for doc in docs:
    DocumentService.model.update(
        progress=0.0, chunk_num=0
    ).where(DocumentService.model.id == doc.id).execute()
    print(f"  {doc.name}: reset")

kb = KnowledgebaseService.query(id=KB_ID)[0]
KnowledgebaseService.model.update(chunk_num=0).where(KnowledgebaseService.model.id == KB_ID).execute()
print(f"KB {kb.name}: chunk_num reset to 0")
print("Done.")
