#!/usr/bin/env python3
"""Reset and re-queue documents in laws_fine_chuncked after the TokenChunker fix.

Two compounding bugs made every existing chunk in this KB wrong and needing
regeneration:
  - Bug 1: TokenChunker mother/child mis-split (fixed in the canvas config by
    fix-tokenchunker-laws-kb-20260717.py) -- existing chunks were split on every
    newline, hiding real content as a disabled "mother" row and showing only
    junk line fragments.
  - Bug 3: SGB_2 and StGB got orphaned mid-index when their task-executor worker
    process died (confirmed via Redis heartbeat inspection -- not the documented
    stranded-stream pattern, so scripts/reclaim-ragflow-tasks.sh does not apply).

Deliberately scoped to this KB's own document IDs only -- does NOT touch the
shared Redis task stream wholesale the way
scripts/reparse-3kbs-post-infinity-wipe-20260711.py does (that script cancels
every in-flight task across every KB in the stack). Also deliberately does NOT
call DocumentService.clear_chunk_num() -- that method decrements
Knowledgebase.doc_num unconditionally, which is exactly how doc_num drifted to -6
in the first place (see fix-docnum-laws-kb-20260717.py and KNOWN_ISSUES.md). This
script replicates only clear_chunk_num()'s harmless half (zeroing the per-document
chunk_num/progress/progress_msg) via a direct update.

Usage: pass one or more document names on the command line to scope the run
(recommended: canary with a single doc first, verify, then run the rest).
No arguments = process all 6 documents in the KB.

    docker cp scripts/reset-and-requeue-laws-kb-20260717.py rag_ai_stack-ragflow-1:/tmp/
    docker exec -i rag_ai_stack-ragflow-1 python3 /tmp/reset-and-requeue-laws-kb-20260717.py BGB.pdf
"""
import sys

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
    assert len(docs) == 6, f"expected 6 docs in {KB_ID}, found {len(docs)} -- abort and investigate"

    wanted = set(sys.argv[1:])
    if wanted:
        docs = [d for d in docs if d.name in wanted]
        missing = wanted - {d.name for d in docs}
        assert not missing, f"requested doc(s) not found in KB: {missing}"

    print(f"KB {KB_ID} ({kb.name!r}), tenant {tenant_id}: resetting {len(docs)} doc(s): {[d.name for d in docs]}")

    for doc in docs:
        print(f"Resetting {doc.name} ({doc.id})")
        cancel_all_task_of(doc.id)
        TaskService.model.delete().where(TaskService.model.doc_id == doc.id).execute()
        DocumentService.model.update(chunk_num=0, progress=0, progress_msg="").where(
            DocumentService.model.id == doc.id
        ).execute()

    for doc in docs:
        fresh = DocumentService.query(id=doc.id)[0].to_dict()
        print(f"Re-queuing {fresh['name']} ({doc.id})")
        DocumentService.run(tenant_id, fresh, {})

    print("Done. Monitor task progress before running the remaining documents.")


if __name__ == "__main__":
    main()
