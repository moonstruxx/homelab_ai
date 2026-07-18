# Known Open Issues

## ragflow: Load term.freq FAIL (WARNING)

**Symptom:** On every startup, each ragflow process logs:
  WARNING:root:Load term.freq FAIL!

**Root cause:** `rag/nlp/term_weight.py` tries to load `rag/res/term.freq`, a Chinese
corpus document-frequency file used for BM25/IDF term weighting. The file has never been
committed to the ragflow GitHub repo and is not included in any official Docker image build
step. No distribution path exists.

**Impact:** The code falls back to `self.df = {}` (empty dict). Short Chinese terms all
receive df=3 (treated as equally rare), degrading Chinese-language full-text search
relevance. English-language content is unaffected — a separate fallback path handles
Latin-alphabet terms correctly.

**Fix:** None available without the original corpus data. An empty placeholder file would
suppress the warning but not improve behaviour. Accepted as a known upstream limitation.

**Decision:** Do not mount an empty term.freq. Warning is harmless for English-language use.

---

## searxng: ahmia / torch engines inactive

**Symptom (resolved):** On startup, SearXNG logged:
  ERROR:searx.engines: loading engine ahmia failed: set engine to inactive!
  ERROR:searx.engines: loading engine torch failed: set engine to inactive!

**Root cause:** Both engines are Tor-dependent (.onion search). No Tor daemon runs in this
stack. `disabled: true` in settings.yml prevents user-facing exposure but still triggers
Python module initialisation, which fails without Tor.

**Fix (applied 2026-06-24):** Changed both entries to `inactive: true` in
`searxng/settings.yml`. This skips the load attempt entirely, suppressing the errors.

---

## elasticsearch: dynamic field mapping limit

**Symptom:** ragflow task executor logs:
  ERROR: Failed to insert metadata for document ...: Limit of total fields [1000] has been exceeded while adding new fields [1]

**Root cause:** Elasticsearch limits dynamic field mappings per index to 1000 by default. RAGFlow maps each unique document metadata key as a separate field; ingesting a large batch of heterogeneous documents (e.g. academic PDFs with varied metadata) exhausts this limit.

**Fix (applied 2026-06-24):** Raised to 5000 on `ragflow*` indices via live `PUT /_settings` call. See CLAUDE.md → "Elasticsearch Field Limit Maintenance" for the command. Repeat when the limit is hit again.

**Note:** The setting is live-only and does not persist to new indices. Long-term fix would be an index template, but the current approach suffices.

---

## ragflow: LLM "unsupported language or locale" error during ingestion

**Symptom:** During RAPTOR summarization or GraphRAG entity extraction, ragflow logs:
  ERROR: OpenAI async completion
  openai.InternalServerError: Error code: 500 - {'reason': 'Error generating response: An unsupported language or locale was used', 'error': True}
  ERROR: async base giving up: MAX_RETRIES_EXCEEDED

**Root cause:** The `apple-on-device` model (`apple-on-dev@OpenAI-API-Compatible` provider, running on macstudio.local via the Apple ANE server) rejects certain inputs with a CoreML/ANE locale error. Observed on ISMIR 2025 proceedings (.docx files) containing LaTeX math notation (e.g. `$ \pm 0.7\% $`).

**Impact:** RAPTOR summaries and GraphRAG entity/community graphs are not built for affected documents. Base chunking and embedding succeed — documents are indexed and searchable, but without the hierarchical RAPTOR layer or graph context.

**Workaround:** Switch the knowledge base's chunk LLM to the apple-on-device-openai model (`macstudio.local:8080`) which handles arbitrary content. Change via RAGFlow UI: Knowledge Base → Settings → Model → LLM.

**Status:** Under investigation. Root cause on the Apple ANE server side not yet confirmed.

---

## paddleocr: PDFium "Data format error" in __images__ (WARNING)

**Symptom:** During PDF ingestion, ragflow task executor logs:
  ERROR: Failed to load document (PDFium: Data format error).
  pypdfium2._helpers.misc.PdfiumError: Failed to load document (PDFium: Data format error).

**Root cause (suspected):** The `__images__` method in `paddleocr_parser.py` renders PDF pages locally in the ragflow container using pypdfium2, for the cropping/thumbnail feature. The error may indicate that binary data fetched from MinIO is being passed to pypdfium2 in an unexpected form — possibly if `EncryptedStorageWrapper` is active and files were stored before encryption was enabled (no magic header, decrypt returns garbage), or if the PDF files are non-standard.

**Impact:** Non-fatal — the exception is caught and execution continues to the `POST /api/v2/ocr/jobs` call, which is the actual OCR path. Text extraction and document indexing succeed regardless. Only the layout-crop/thumbnail feature is degraded.

**Investigation:** `docker exec rag_ai_stack-ragflow-1 env | grep RAGFLOW_CRYPTO` — if `RAGFLOW_CRYPTO_ENABLED=true`, verify `CryptoUtil.decrypt()` (`ragflow/common/crypto_utils.py`) returns original bytes unchanged when the `RAGF` magic header is absent.

**Status:** Under investigation. Not blocking ingestion.

---

## ragflow: sniffio AsyncLibraryNotFoundError during async stream GC (Exception ignored)

**Symptom:** ragflow logs emit pairs of `Exception ignored in:` tracebacks during LLM calls:
  Exception ignored in: <async_generator object AsyncStream.__stream__ at 0x...>
  sniffio._impl.AsyncLibraryNotFoundError: unknown async library, or not in async context
  Exception ignored in: <async_generator object HTTP11ConnectionByteStream.__aiter__ at 0x...>
  sniffio._impl.AsyncLibraryNotFoundError: unknown async library, or not in async context

**Root cause:** Two-part:
1. `httpcore` 1.0.9 (bundled in the ragflow venv) calls `sniffio.current_async_library()` eagerly in `AsyncShieldCancellation.__init__`. When Python 3.13's GC finalizes an abandoned async generator outside an event loop, sniffio cannot find the async library and raises `AsyncLibraryNotFoundError`. Fixed upstream in httpcore ≥ 1.0.10.
2. The streams are abandoned (not `aclose()`d) because an exception in RAGFlow's LLM calling code unwinds the stack without closing the httpx/openai response. The most common trigger is the Apple ANE locale error (see above).

**Impact:** Non-fatal — `Exception ignored in:` means Python swallows these during GC. LLM calls and document indexing are unaffected. Abandoned connections may not return to the httpcore pool cleanly, causing gradual pool bloat over extended uptime.

**Fix options:**
- Upgrade httpcore in the ragflow venv (`pip install 'httpcore>=1.0.10'` inside the container, or pin it in the image build). Not persistent across container rebuilds without a Dockerfile change.
- Eliminate the underlying LLM error: switch affected knowledge bases from the Apple ANE model to the apple-on-device-openai model (see "LLM unsupported language or locale error" above). Removes the most common trigger.

**Status:** Known noise. Monitor connection pool health if ragflow becomes unresponsive to LLM calls after long uptime.

---

## searxng: X-Forwarded-For header missing (WARNING)

**Symptom:** Periodic log entry:
  ERROR:searx.botdetection: X-Forwarded-For nor X-Real-IP header is set!

**Root cause:** Health-check or direct requests to SearXNG arrive without forwarding
headers. `forwarded_allow_ips: "*"` is set in settings.yml, but the botdetection module
still logs when the headers are absent.

**Impact:** Cosmetic. SearXNG responds normally; no requests are blocked.

**Fix:** None needed. The warning is non-actionable for an internal-only deployment.

---

## ragflow pipeline: TokenChunker `children_delimiters` mis-split hides real content, shows junk fragments (2026-07-17)

**Symptom:** For KB `laws_fine_chuncked`: documents parsed successfully, but browsing
a document's chunks showed every chunk as "disabled", and the KB overview showed 0
chunks total despite chunks clearly existing.

**Root cause:** The KB's ingestion dataflow ("laws adv llmm" canvas) has a
`TokenChunker` node with `enable_children: true`. RAGFlow's mother/child chunking
(`rag/svr/task_executor_refactor/chunk_service.py::_create_mother_chunks`, same
logic in the legacy `rag/svr/task_executor.py`) takes the pre-split text as a
synthetic "mother" context row and unconditionally writes it with
`available_int=0` (hidden by design); every fragment produced by splitting on
`children_delimiters` becomes a visible "child" row (default `available_int=1`).
The node's `children_delimiters` was `["\n"]` — splitting on every single
newline. For this KB's German statutory PDFs (MinerU output has short per-line
text with no blank-line paragraph breaks — confirmed 0/327 sampled mother rows
contain `\n\n`), that shredded each real ~1000-2000 char section into ~12 tiny
6-124 char line fragments as the visible children, while the complete real
section text sat hidden as the mother row. This is stock upstream RAGFlow
behaviour working exactly as designed — a KB dataflow misconfiguration, not a
code bug (confirmed no fork-local commits touch this logic).

A second, independent bug compounded the "0 chunks" symptom: `knowledgebase.chunk_num`/
`document.chunk_num` were stuck at 0 in MySQL for this KB (see the
`DocumentService.clear_chunk_num` entry below) — the KB overview reads these MySQL
columns directly (`api/apps/services/dataset_api_service.py`), not a live filtered
query against the doc store, so genuinely-existing chunks with a stale MySQL count
still show "0" in the overview.

**Fix applied:** Changed `children_delimiters` to `["\n§ ", "\nArt "]` —
confirmed via live sampling to reliably match only true section/article headers in
this corpus (472 clean line-start `\n§ ` occurrences, 190 clean `\nArt `, 0 false
positives against inline `§` cross-references like `dem § 126`), producing ~3
children per mother (target 2-6) instead of ~12 junk fragments. Matches the
convention the pipeline's own upstream `TitleChunker` node already uses (its
hierarchy levels treat `^§ ` and `^Art [0-9]+` as structural boundaries). Applied
via `scripts/fix-tokenchunker-laws-kb-20260717.py`, then all 6 documents were
reset and re-queued via `scripts/reset-and-requeue-laws-kb-20260717.py` (staged:
canary doc first, then the rest — see CLAUDE.md's 2026-07-17 entry for the full
incident writeup).

**Takeaway for other KBs:** any pipeline-based ingestion canvas using
`TokenChunker` with `enable_children: true` should have its `children_delimiters`
checked against real sample text before relying on the mother/child hierarchy —
`["\n"]` (a common copy-paste default) only works for source text with genuine
blank-line paragraph breaks; it silently inverts "real content vs. fragment"
visibility for anything more line-fragmented (much OCR/MinerU output, verse/legal
text, tables-as-text, etc.).

**Status:** Resolved for `laws_fine_chuncked`. Not yet audited across other KBs
using pipeline ingestion with `enable_children: true`.

---

## ragflow: `DocumentService.clear_chunk_num()` misuse decremented `knowledgebase.doc_num` (2026-07-17)

**Symptom:** `knowledgebase.doc_num` for `laws_fine_chuncked` read `-6` instead of
the real count of 6 documents; `chunk_num` was stuck at 0 in MySQL despite real
chunks existing in Infinity for several documents.

**Root cause:** `DocumentService.clear_chunk_num()` (`api/db/services/document_service.py`)
is docstring-marked `"""Deprecated: use delete_document_and_update_kb_counts
instead."""` and unconditionally does `Knowledgebase.doc_num - 1` — a decrement
appropriate only when a document is actually being deleted. Two incident-response
scripts (`scripts/reparse-3kbs-post-infinity-wipe-20260711.py`, run once on
2026-07-11 and again on 2026-07-12 after unrelated Infinity-crash data wipes) called
this method purely to zero `chunk_num`/`progress` before **re-queuing** documents
for re-parsing — not deleting them — so each of the 2 runs silently decremented
`doc_num` by 1 for each of this KB's 6 real documents (2 × 6 = -12 off a baseline
of 6 → -6). The project's own documented "single-document reset+requeue pattern"
(CLAUDE.md, originally written for the 2026-07-11 img2txt VLM hang) also called
this same method and carried the same bug — anyone copy-pasting that pattern for
a future incident would keep re-introducing this drift.

**Fix applied:** One-time correction via `scripts/fix-docnum-laws-kb-20260717.py`
(sets `doc_num` to the real `COUNT(*)` of documents in the KB). CLAUDE.md's
documented single-document reset pattern was corrected to drop the
`clear_chunk_num()` call — it's redundant anyway, since the pattern already zeroes
`chunk_num`/`progress`/`progress_msg` via a direct `.update()` one line above it.

**Status:** Resolved for `laws_fine_chuncked`. Any other KB that had documents
reset via `reparse-3kbs-post-infinity-wipe-20260711.py` or an incident script that
copy-pasted the old CLAUDE.md pattern should have its `doc_num` spot-checked
against a real document count.
