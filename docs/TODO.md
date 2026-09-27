# Deferred work (not implemented)

- exec_command: explicitly requested, postponed until current storage/permissions are stable. A cwd restriction is NOT a filesystem sandbox; reassess every file/key boundary before adding execution.
- Context compression preserving stable IDs and history provenance.
- General ordered-block / Responses / Anthropic / multimodal provider adapters; do not silently flatten into Chat Completions.
- Incremental history persistence to reduce full-ctx checkpoint write amplification, without losing completed tool results.
- Optional edit_file/search_files and richer directory metadata after core runner validation.
- Profile-safe upgrade workflow (overlay ZIP extraction can overwrite configured profile files).
- Live v0.3 DeepSeek/OpenAI/Tavily integration and adversarial prompt-injection evaluation.

Not planned in current scope: task --json, automatic provider routing, built-in DNS repair, legacy CLI/storage migration, OS-level isolation claims.
