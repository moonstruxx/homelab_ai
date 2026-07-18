#!/usr/bin/env python3
"""Verify laws_fine_chuncked KB has proper chunk counts after re-parse.

Expected chunk counts (German law, delimiter='\\n§ '):
- GG.pdf (Grundgesetz): ~900-1000 chunks
- BGB.pdf: ~800-1000 chunks  
- StGB.pdf: ~300-400 chunks
- HGB.pdf: ~500-700 chunks
- SGB_1.pdf: ~200-300 chunks
- SGB_2.pdf: ~150-250 chunks

Total expected: ~3000-4000 chunks
"""
from common import settings
settings.init_settings()
from api.db.services.document_service import DocumentService
from api.db.services.knowledgebase_service import KnowledgebaseService

KB_ID = "65d9f3367cd111f19b6e25d679132943"

kb = KnowledgebaseService.query(id=KB_ID)[0]
print(f"KB: {kb.name}")
print(f"KB chunk_num: {kb.chunk_num}")
print(f"KB doc_num: {kb.doc_num}")
print(f"Parser delimiter: {kb.parser_config.get('delimiter')!r}")
print()

docs = DocumentService.model.select().where(DocumentService.model.kb_id == KB_ID)
total_chunks = 0
all_done = True

for doc in docs:
    status = "✓" if float(doc.progress) >= 1.0 else "⏳"
    print(f"{status} {doc.name}: progress={doc.progress:.1%}, chunk_num={doc.chunk_num}")
    total_chunks += doc.chunk_num
    if float(doc.progress) < 1.0:
        all_done = False

print()
print(f"Total chunks: {total_chunks}")
print(f"All documents complete: {'Yes' if all_done else 'No'}")

# Verification criteria
expected_min_chunks = 2500
expected_max_chunks = 4500
if all_done and expected_min_chunks <= total_chunks <= expected_max_chunks:
    print(f"✓ VERIFICATION PASSED: {total_chunks} chunks in expected range ({expected_min_chunks}-{expected_max_chunks})")
elif all_done and total_chunks < expected_min_chunks:
    print(f"⚠ VERIFICATION WARNING: {total_chunks} chunks below expected minimum ({expected_min_chunks})")
elif all_done and total_chunks > expected_max_chunks:
    print(f"⚠ VERIFICATION WARNING: {total_chunks} chunks above expected maximum ({expected_max_chunks})")
else:
    print("⏳ Re-parse still in progress, verification pending...")
