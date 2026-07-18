#!/usr/bin/env python3
"""Serially re-parse all 6 documents in laws_fine_chuncked, one at a time.

Must run strictly sequential, not concurrent: an earlier attempt at re-parsing
multiple documents in this KB at once triggered a task-executor concurrency bug
(repeated `RuntimeError: Attempted to exit cancel scope in a different task than
it was entered in` from anyio/httpcore under concurrent async load) that silently
failed one document's indexing step across 4 retries. Infinity chunks for all 6
documents have already been wiped clean (scripts/wipe-and-serial-requeue-laws-kb-20260717.py
plus manual follow-up deletes after a stuck-lock incident required an Infinity
restart) and MySQL task/progress state reset to 0. This script queues one
document, polls until it finishes (progress==1) or fails (progress==-1) or times
out, then moves to the next -- never two in flight at once.

    docker cp scripts/serial-requeue-laws-kb-20260717.py rag_ai_stack-ragflow-1:/tmp/
    docker exec -i rag_ai_stack-ragflow-1 python3 -u /tmp/serial-requeue-laws-kb-20260717.py
"""
import time

from common import settings

settings.init_settings()
from api.db.services.document_service import DocumentService
from api.db.services.knowledgebase_service import KnowledgebaseService

KB_ID = "65d9f3367cd111f19b6e25d679132943"
POLL_INTERVAL_S = 15
PER_DOC_TIMEOUT_S = 40 * 60  # MinerU can take 10-20 min/doc; generous margin


def main():
    kb = KnowledgebaseService.query(id=KB_ID)[0]
    tenant_id = kb.tenant_id
    docs = list(DocumentService.model.select().where(DocumentService.model.kb_id == KB_ID))
    assert len(docs) == 6, f"expected 6 docs, found {len(docs)}"

    results = {}
    for doc in docs:
        print(f"=== Starting {doc.name} ({doc.id}) ===", flush=True)
        fresh = DocumentService.query(id=doc.id)[0].to_dict()
        DocumentService.run(tenant_id, fresh, {})

        t0 = time.time()
        final_progress = None
        while time.time() - t0 < PER_DOC_TIMEOUT_S:
            time.sleep(POLL_INTERVAL_S)
            d = DocumentService.query(id=doc.id)[0]
            print(f"  [{int(time.time()-t0)}s] progress={d.progress} chunk_num={d.chunk_num}", flush=True)
            if float(d.progress) >= 1.0 or float(d.progress) < 0:
                final_progress = float(d.progress)
                break
        else:
            print(f"  TIMEOUT after {PER_DOC_TIMEOUT_S}s, moving on", flush=True)
            final_progress = "timeout"

        d = DocumentService.query(id=doc.id)[0]
        results[doc.name] = {"progress": final_progress, "chunk_num": d.chunk_num}
        print(f"=== Finished {doc.name}: progress={final_progress} chunk_num={d.chunk_num} ===\n", flush=True)

    print("\n=== SUMMARY ===", flush=True)
    for name, r in results.items():
        print(f"{name}: {r}", flush=True)


if __name__ == "__main__":
    main()
