1|# Open Issues - RAGFlow `laws_fine_chunked` Knowledge Base
2|
3|**Date**: 2026-07-18 04:30  
4|**KB**: `laws_fine_chunked` (German Gesetzesbücher: BGB, StGB, GG, HGB, SGB_1, SGB_2)  
5|**Status**: ⏳ Re-parse in progress with corrected delimiter '\n§ '
6|
7|> **Key Insight**: Detailed procedures are in the RAGFlow skills:
8|> - `ragflow-kb-management` - MySQL counter fix, concurrent re-parse bug, serial discipline
9|> - `ragflow-operations` - German law chunking configuration, troubleshooting
10|
11|---
12|
13|## Issue 1: MySQL Chunk Counters Stuck at 0
14|
15|**Status**: ✅ Resolved (2026-07-18)  
16|**Fix Applied**: `scripts/fix-docnum-laws-kb-20260717.py` corrected `knowledgebase.doc_num` from -6 to 6.
17|**Current State**: MySQL counters show correct values (doc_num=6, chunk_num updates during re-parse).

---
28|
29|## Issue 2: Suboptimal Chunking Delimiter for German Law Texts
30|
31|**Status**: ✅ Fixed (2026-07-18)  
32|**Fix Applied**: `scripts/fix-kb-parser-config-laws.py` updated delimiter from `'\n'` to `'\n§ '`.
33|**Current Config**: `delimiter: '\n§ '`, `enable_children: false`
34|**Expected Result**: Section-level chunks (~3 children/mother instead of line-level fragments).
35|- GG.pdf should produce ~900-1000 chunks
36|- BGB.pdf should produce ~800-1000 chunks
37|
38|---
39|
40|## Issue 3: Re-parse in Progress
41|
42|**Status**: ⏳ Running (Started 2026-07-18 04:26)  
43|**Action**: Serial re-parse of all 6 documents with corrected delimiter.
44|**Script**: `scripts/serial-requeue-laws-kb-20260717.py` running in container.
45|**Timeline**: ~60-120 minutes for all documents (MinerU parsing is slow for German law PDFs).
46|
47|**Current Progress**:
48|- BGB.pdf: 0.03% (processing, MinerU parsing)
49|- GG.pdf, HGB.pdf, SGB_1.pdf, SGB_2.pdf, StGB.pdf: 0% (queued)
50|
51|**Next Steps**:
52|1. Wait for serial re-parse to complete (monitor with script below)
53|2. Run `scripts/verify-laws-kb-chunks.py` to verify chunk counts
54|3. Perform retrieval test (sample queries against German law sections)

---

## Issue 3: Incomplete Document Processing

**Status**: 🟡 Partial  
**Documents with Errors**:
- `StGB.pdf`: Multiple `handle_task got exception` entries in logs
- `BGB.pdf`: Had errors before eventual success (retry count > 0)
- `GG.pdf`: Had errors during processing

**Documents Completed Successfully**:
- `SGB_2.pdf`: 4 chunks (05:12, 10:38)
- `HGB.pdf`: Completed (06:14)
- `SGB_1.pdf`: Completed (06:15)

**Root Cause**: Mixed - some documents hit Infinity delete hangs, others hit task executor errors under concurrent load.

**Recommended Action**:
1. Fix MySQL counters first (Issue 1)
2. Update parser config (Issue 2)
3. Re-parse all 6 documents **serially** (never concurrently - see CLAUDE.md concurrency bug note)
4. Verify chunk counts and content quality

---

## Issue 4: Serial Re-queue Process Stopped

**Status**: 🟢 Resolved (Process Killed Intentionally)  
**Background**: A serial re-queue script (`scripts/serial-requeue-laws-kb-20260717.py`) was started but got stuck on `BGB.pdf` at progress 0.002 (0.2%) for 28+ minutes. The process was killed.

**Current State**: No active re-parse process running. Documents remain in their last state (some completed, some errored).

**Recommended Action**: After fixing counters and config, restart serial re-parse with proper timeouts and monitoring.

---

## Action Plan

**See skills for detailed procedures:**
- `ragflow-kb-management` - MySQL counter fix, serial re-parse discipline
- `ragflow-operations` - German law chunking configuration

### Phase 1: Fix MySQL Counters
```bash
# Create and run scripts/fix-mysql-counters-laws-kb.py
# Based on ragflow-kb-management skill pattern
```

### Phase 2: Update Parser Configuration  
```bash
# Update KB parser config delimiter to "\n§ "
# See ragflow-operations skill → "German Law Texts"
```

### Phase 3: Re-parse All Documents Serially
```bash
# Use serial re-parse driver (see ragflow-kb-management skill)
# Never concurrent - one document at a time
```

### Phase 4: Verify
```bash
# Check UI shows correct chunk counts
# Sample chunk content (section-level, not line-level)
# Test retrieval quality
```

---

## References

**Skills** (primary source for procedures):
- `ragflow-kb-management` - MySQL counter fix, concurrent re-parse bug, serial discipline
- `ragflow-operations` - German law chunking config, troubleshooting
- `ragflow-operations/references/german-law-chunking.md` - Detailed analysis of German law structure

**Logs**:
- Task executor: `/ragflow/logs/task_executor_common_*.log` (on nuc25.local)
- Serial requeue: `/tmp/serial-requeue.log` (on nuc25.local)

**CLAUDE.md**:
- `nuc25.local/CLAUDE.md` lines 444-463: Incident history (2026-07-17)
- `nuc25.local/KNOWN_ISSUES.md` - Other active issues

**Scripts** (to be created based on skill patterns):
- `scripts/fix-mysql-counters-laws-kb.py`
- `scripts/fix-tokenchunker-delimiters.py` (already exists from earlier fix)
- `scripts/serial-requeue-driver.py` (already exists)
