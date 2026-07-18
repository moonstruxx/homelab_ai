#!/usr/bin/env python3
"""Fix KB parser_config delimiter for laws_fine_chuncked.

Current: delimiter='\\n' (splits every line)
Target:  delimiter='\\n§ ' (splits at section boundaries)

This updates the knowledgebase.parser_config directly, then documents
need to be re-parsed to produce proper section-level chunks.

Run inside ragflow container:
    docker cp scripts/fix-kb-parser-config-laws.py rag_ai_stack-ragflow-1:/tmp/
    docker exec -i rag_ai_stack-ragflow-1 python3 /tmp/fix-kb-parser-config-laws.py
"""
from common import settings
settings.init_settings()
from api.db.services.knowledgebase_service import KnowledgebaseService

KB_ID = "65d9f3367cd111f19b6e25d679132943"
TARGET_DELIMITER = "\n§ "


def main():
    kb = KnowledgebaseService.query(id=KB_ID)[0]
    old_config = kb.parser_config
    old_delim = old_config.get("delimiter", "NOT_SET")
    
    print(f"KB: {kb.name} ({KB_ID})")
    print(f"Current delimiter: {old_delim!r}")
    
    assert old_delim == "\n", f"Unexpected delimiter {old_delim!r}, aborting"
    
    # Update delimiter in parser_config
    old_config["delimiter"] = TARGET_DELIMITER
    KnowledgebaseService.update_by_id(KB_ID, {"parser_config": old_config})
    
    # Verify
    reloaded = KnowledgebaseService.query(id=KB_ID)[0]
    new_delim = reloaded.parser_config.get("delimiter")
    assert new_delim == TARGET_DELIMITER, f"Expected {TARGET_DELIMITER!r}, got {new_delim!r}"
    
    print(f"Updated delimiter -> {TARGET_DELIMITER!r}")
    print("Next step: Re-parse all documents to generate proper chunks")


if __name__ == "__main__":
    main()
