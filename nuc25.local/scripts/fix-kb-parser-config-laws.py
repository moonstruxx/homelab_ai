#!/usr/bin/env python3
"""Fix KB parser_config delimiter for laws_fine_chuncked."""
from common import settings
settings.init_settings()
from api.db.services.knowledgebase_service import KnowledgebaseService

KB_ID = "65d9f3367cd111f19b6e25d679132943"
TARGET_DELIMITER = "\n§ "

kb = KnowledgebaseService.query(id=KB_ID)[0]
old_delim = kb.parser_config.get("delimiter")
print(f"KB: {kb.name}, current delimiter: {old_delim!r}")
assert old_delim == "\n", f"Unexpected: {old_delim!r}"

kb.parser_config["delimiter"] = TARGET_DELIMITER
KnowledgebaseService.update_by_id(KB_ID, {"parser_config": kb.parser_config})

reloaded = KnowledgebaseService.query(id=KB_ID)[0]
assert reloaded.parser_config.get("delimiter") == TARGET_DELIMITER
print(f"Updated delimiter -> {TARGET_DELIMITER!r}")
print("Next: Re-parse documents to generate proper chunks")
