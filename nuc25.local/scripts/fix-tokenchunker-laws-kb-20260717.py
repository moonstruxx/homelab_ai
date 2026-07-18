#!/usr/bin/env python3
"""Fix TokenChunker children_delimiters for the laws_fine_chuncked KB's ingestion
canvas ("laws adv llmm", id 979281ea7cc711f1a7d8dd598ccf016b).

Bug: children_delimiters was ["\n"], splitting every newline. RAGFlow's mother/child
chunking (rag/svr/task_executor_refactor/chunk_service.py::_create_mother_chunks)
hides the pre-split "mother" text (available_int=0) and shows only the split
fragments as visible children (available_int=1) -- with a per-newline split on this
KB's German statutory PDFs, the full real section text (1000-2000+ chars) ends up
hidden and dozens of 6-124 char line fragments end up visible. Confirmed via live
Infinity sampling (327 mother rows, BGB/GG/SGB_1): 0/327 contain "\n\n" (blank-line
split is a dead end for this MinerU output), but "\n§ " (line-start "§ ") and
"\nArt " reliably mark real section/article headers (472 and 190 clean line-start
occurrences respectively, 0 false positives in spot checks) and produce ~3
children/mother (target: 2-6), vs. ~12 under the old delimiter. This also matches
the upstream TitleChunker node's own hierarchy levels, which already treat
"^§ " and "^Art [0-9]+" as structural boundaries -- same convention, not a new one.

See KNOWN_ISSUES.md ("TokenChunker children_delimiters mis-split") for the general
failure class. Run inside the ragflow container:
    docker cp scripts/fix-tokenchunker-laws-kb-20260717.py rag_ai_stack-ragflow-1:/tmp/
    docker exec -i rag_ai_stack-ragflow-1 python3 /tmp/fix-tokenchunker-laws-kb-20260717.py
"""
import json

from common import settings

settings.init_settings()
from api.db.services.canvas_service import UserCanvasService

CANVAS_ID = "979281ea7cc711f1a7d8dd598ccf016b"
NODE_ID = "TokenChunker:TwoNeedlesInvite"
NEW_DELIMITERS = ["\n§ ", "\nArt "]


def main():
    canvas = UserCanvasService.query(id=CANVAS_ID)[0]
    dsl = json.loads(canvas.dsl) if isinstance(canvas.dsl, str) else canvas.dsl

    params = dsl["components"][NODE_ID]["obj"]["params"]
    old = params["children_delimiters"]
    print(f"Canvas {CANVAS_ID} ({canvas.title!r}) node {NODE_ID}")
    print(f"  children_delimiters: {old!r} -> {NEW_DELIMITERS!r}")
    assert old == ["\n"], f"unexpected current value {old!r}, aborting to avoid clobbering an unrelated edit"

    params["children_delimiters"] = NEW_DELIMITERS
    UserCanvasService.update_by_id(CANVAS_ID, {"dsl": json.dumps(dsl)})

    reloaded = UserCanvasService.query(id=CANVAS_ID)[0]
    reloaded_dsl = json.loads(reloaded.dsl) if isinstance(reloaded.dsl, str) else reloaded.dsl
    persisted = reloaded_dsl["components"][NODE_ID]["obj"]["params"]["children_delimiters"]
    assert persisted == NEW_DELIMITERS, f"persisted value {persisted!r} does not match intended {NEW_DELIMITERS!r}"
    print("Verified persisted:", persisted)


if __name__ == "__main__":
    main()
