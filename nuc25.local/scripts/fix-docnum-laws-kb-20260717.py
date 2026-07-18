#!/usr/bin/env python3
"""Correct knowledgebase.doc_num for laws_fine_chuncked, which drifted to -6.

Root cause: scripts/reparse-3kbs-post-infinity-wipe-20260711.py (run 2026-07-11 and
again 2026-07-12 after Infinity crash wipes) called the deprecated
DocumentService.clear_chunk_num() purely to zero chunk_num/progress before
re-queuing documents. clear_chunk_num() docstring: "Deprecated: use
delete_document_and_update_kb_counts instead." -- it unconditionally decrements
Knowledgebase.doc_num by 1, a side effect meant only for genuine document deletion.
2 script runs x 6 real docs x -1 = -12 off a baseline of 6 -> -6.

chunk_num is NOT corrected here -- it self-heals via DocumentService.increment_chunk_num()
calls in the normal ingestion path once documents are re-parsed under the corrected
TokenChunker config (see fix-tokenchunker-laws-kb-20260717.py and
reset-and-requeue-laws-kb-20260717.py).

See KNOWN_ISSUES.md ("DocumentService.clear_chunk_num misuse"). Run inside the
ragflow container:
    docker cp scripts/fix-docnum-laws-kb-20260717.py rag_ai_stack-ragflow-1:/tmp/
    docker exec -i rag_ai_stack-ragflow-1 python3 /tmp/fix-docnum-laws-kb-20260717.py
"""
from common import settings

settings.init_settings()
from api.db.services.document_service import DocumentService
from api.db.services.knowledgebase_service import KnowledgebaseService

KB_ID = "65d9f3367cd111f19b6e25d679132943"


def main():
    kb = KnowledgebaseService.query(id=KB_ID)[0]
    real_count = DocumentService.model.select().where(DocumentService.model.kb_id == KB_ID).count()
    print(f"KB {KB_ID} ({kb.name!r}): current doc_num={kb.doc_num}, real document count={real_count}")

    KnowledgebaseService.model.update(doc_num=real_count).where(KnowledgebaseService.model.id == KB_ID).execute()

    reloaded = KnowledgebaseService.query(id=KB_ID)[0]
    assert reloaded.doc_num == real_count, f"expected doc_num={real_count}, got {reloaded.doc_num}"
    print(f"Corrected doc_num -> {reloaded.doc_num}")


if __name__ == "__main__":
    main()
