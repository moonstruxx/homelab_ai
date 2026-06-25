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

**Workaround:** Switch the knowledge base's chunk LLM to the MLX Studio model (MLX Gateway on `macstudio.local:8080`) which handles arbitrary content. Change via RAGFlow UI: Knowledge Base → Settings → Model → LLM.

**Status:** Under investigation. Root cause on the Apple ANE server side not yet confirmed.

---

## searxng: X-Forwarded-For header missing (WARNING)

**Symptom:** Periodic log entry:
  ERROR:searx.botdetection: X-Forwarded-For nor X-Real-IP header is set!

**Root cause:** Health-check or direct requests to SearXNG arrive without forwarding
headers. `forwarded_allow_ips: "*"` is set in settings.yml, but the botdetection module
still logs when the headers are absent.

**Impact:** Cosmetic. SearXNG responds normally; no requests are blocked.

**Fix:** None needed. The warning is non-actionable for an internal-only deployment.
