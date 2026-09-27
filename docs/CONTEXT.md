# Context and compiler (schema 1)

```json
{
  "schema_version":1,
  "msgs":[{"msg_id":2,"evt_ids":[2,3],"format":"chat_completions","complete":true}],
  "events":[
    {"evt_id":2,"timestamp":"2026-09-27T07:00:03Z","kind":"assistant_content","value":"让我看看"},
    {"evt_id":3,"timestamp":"2026-09-27T07:00:03Z","kind":"tool_call","value":{"id":"call_123","type":"function","function":{"name":"read_file","arguments":"{\"path\":\"/workspace/inbox/文档.md\"}"}}}
  ]
}
```

The example ends with a pending tool request; it is queryable, not a complete valid next-request transcript until feedback is recorded.

## Authority and order

`ctx.json` is historical truth, body values stored once. msgs only organize ordered evt_ids, not a duplicate role/content. Kinds: user_content; assistant_content; reasoning_content; tool_call; tool. All tool_call or all reasoning_content also infer assistant. Repeated kinds and content/tool-call interleaving allowed; do not reorder by kind. Tool feedback value contains tool_call_id + content. Native function.arguments remains its original string (strict parsed copy for tool execution, no regex guessing).

Message metadata is limited: format describes source representation, complete marks streaming completeness, native may retain name/refusal. No role or duplicate body there. All timestamps UTC Z, may equal. Timestamp is observation time, not inaccessible model-internal timing.

Explicit source/block order wins; otherwise raw JSON object's field occurrence order and array order assign event IDs. CLI writes user content directly with an input milestone time. Event allocation monotonic; logical order is msgs array / evt_ids. Historical insertion creates new high IDs at old logical positions without renumbering. Deleting/clearing does not reset high-water counters in info.json. Fork ctx/all inherits counters including previously discarded IDs; fork conf starts empty counters under a new session ID.

## Raw viewing

Canonical file is JSON with each msg and each event record on one line. An evt query copies the stored event record; msg query copies stored organization and referenced records. No summary, no time injection, no provider compilation. This means **ctx raw record**, not a second saved HTTP envelope or original wire JSON whitespace. APIs' content/arguments strings remain preserved. Raw queries can expose private data or provider reasoning if explicitly requested; they are not the normal task output.

ID-range selection is numeric selection, not guaranteed contiguous logical conversation after edits. Selected records remain in stored file order; evt_ids explicitly expresses message-local logical order. Oversize terminal queries refuse before writing stdout. Full export copies source bytes even if provider compilation would fail.

## Compiler passes

1. Validate schema/unique IDs, references, exclusive event ownership, compatible kind families.
2. Skip empty message groups with located, deduplicated warning. Skip incomplete messages, preserving completed stored blocks for inspection.
3. Restore supported Chat Completions native fields. Text fragments concatenate exactly, no invented separator; null mixed with other content cannot silently concatenate. Native content null/empty/missing distinguished. Explicit empty tool_calls null/[] gets its own evt; missing tool_calls doesn't.
4. Validate tools: within-request call IDs distinct, results match pending IDs, no inserted non-tool message before all requested results. Reused call IDs in later fully paired turns are allowed. Incomplete pairing is critical—compiler does not invent tool results or move user messages.
5. Adapt provider: supported native reasoning replay for DeepSeek; OpenAI projection omits unsupported reasoning with warning, does not delete old data. Input format other than supported Chat Completions causes a located incompatibility rather than silently flattening arbitrary block semantics.
6. Inject one `[UTC <timestamp>]` prefix into the compiled user content (first user evt's timestamp). Original stored contents never acquire prefixes. Multiple user evt timestamps still available in ctx; editing an evt updates only that evt. Rerun does not update original input time. All per-request tools/system capabilities are dynamic and not written into transcript.

Compilation is a pure memory projection with explicit whitelists. Same context/provider yields same request messages. It does not infer whether an old answer is coherent after user edits. Error diagnostic IDs locate data; raw query/export do not require compilation success.

## Streaming and persistence

SSE decoder retains field/chunk ordering. When a logical content block or indexed tool call starts, reserve one evt ID; more deltas extend its buffer. Not an evt per token. Text boundary or explicit completion permits persistence; tool JSON parsing alone is NOT a completion signal, so Chat Completions tool arguments wait for finish_reason. Multiple concurrently streamed calls keyed by provider index. Streaming null text deltas mean no text fragment; empty tool_calls values are represented explicitly. Source raw wire chunks are not a separate permanent history.

On normal finish, publish a complete message and execute complete tool calls. On disconnect/cancellation/length finish, discard uncompleted buffered blocks, never execute partial calls or use partial text as fallback. Already-completed blocks stay queryable, their incomplete message is not compiled as complete. Nonstream truncation provides no reliable internal boundaries, so content from that response is not treated as a completed answer. High-water IDs remain reserved; gaps are legal.

Events completed before a tool side effect are saved; each tool result saved on return. Per-session transaction journal makes ctx/config/info write groups recoverable. Index has its own short, redoable mutation journal and backup. Backups are not blindly auto-applied to damaged indexes. Global index lock never spans network execution. Session/run/lifecycle locks remain outside removable session directories.

This release still rewrites a ctx snapshot at completed-block checkpoints, not an append-only compressed database. Large histories can have write amplification; correctness precedes incremental storage. No future compression functionality is claimed.
