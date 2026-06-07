# 2026-06-05 Memory System Next Plan

## Goal

This is not a rewrite. The goal is to make the existing memory stack easier to reason about:

- Long natural messages should recall better when they mix emotion, background, current task, metaphors, names, and casual side mentions.
- Long-term user context should have a clear place that is separate from Core Memory and dynamic recall.
- LLM-maintained memory should stay evidence-bound: it may propose updates, but it must not silently rewrite roots.

## Current Facts

- Gateway currently uses the current user message as one recall query in normal bucket mode or graph mode.
- The existing recall path already has deterministic term extraction, context-term filtering, facet expansion, topic evidence, vague gates, budget, cooldown, and `RecallPolicy`.
- Gateway now has an optional LLM query planner that splits long mixed messages into short search anchors.
- `core_memory_interval_rounds` defaults to `0`, so Core Memory injection is off unless configured.
- When enabled, Gateway's Core Memory block only takes `pinned` or `protected` buckets.
- `memory_layers.py` classifies ordinary `permanent` buckets as core layer, but Gateway does not inject ordinary permanent buckets into the Core Memory block.

This means the next change should clarify boundaries before adding more automatic behavior.

## 2026-06-06 Status Update

The current slice is complete on `feature/memory-diffusion-p0`.

- Private Alias is live as a deployment-private overlay, not a template feature. The VPS uses `/state/private_identity_semantics.yaml`, derived from the previous `reflection.identity_role_edges`. `config.example.yaml` keeps `identity_semantics` empty. The rebuilt live index has `8` canonical nodes, `12` aliases, and `21` evidence links.
- Word Map Lite and private identity diagnostics are implemented as dashboard/manual rebuild tooling. They do not inject anything into Gateway by themselves.
- `scripts/migrate_affect_anchor_sections.py` migrates old bucket structure without rewriting memory meaning:
  - facts move to `### moment`
  - Haven interpretations such as `Haven 由此确认...` move to `### assistant_reflection`
  - `### affect_anchor` keeps only chords, `含义：...`, and temperature/poetic markers
  - duplicate short facts are skipped when already covered by longer body text
- The migration also handles the unheaded-body case where a reflection paragraph was written in the main body without a `### assistant_reflection` heading.
- Live VPS migration was applied after dry-run review:
  - first `2c4b82ee93ba` and `reflection_daily_2026-06-05`
  - then `65023203392f`
  - then the remaining 53 default-scope buckets
- Final verification:
  - default dry-run: `0` remaining
  - `--include-archive` dry-run: `0` remaining
  - every applied bucket reported `written=true`, `embedding_refreshed=true`, and `moment_index_refreshed=true`
  - `breath(query="激动哭")` hits `2c4b82ee93ba`
  - `breath(query="记忆改版 模型更新")` hits `65023203392f` and returns the new `### assistant_reflection`

## 2026-06-07 Status Update

New tool-written memories now keep the target structure at write time.

- Runtime fix: commit `73660a9` (`Wrap unheaded memory writes as moments`) on `feature/memory-diffusion-p0`.
- `_normalize_memory_sections_for_write()` now calls the migration planner with `body_only_moment="wrap"` for server write paths.
- This affects `hold`, `grow`, digest items, merges, and `/api/memories` writes.
- If a new write starts with unheaded body text and has no existing/extracted `### moment`, the leading body is wrapped as `### moment`.
- Existing old-bucket migration stays conservative: the CLI/default dry-run still uses `body_only_moment="skip"`, so pure old body-only buckets are not suddenly pulled into migration plans.
- Guardrail cases are covered:
  - unheaded body + `### reflection` + chord-only `### affect_anchor` becomes `### moment` + `### reflection` + `### affect_anchor`
  - if `### affect_anchor` already yields an event moment, the leading body is preserved rather than duplicated
  - if an explicit `### moment` already exists, the leading body is left alone
- Validation before deploy: `31 passed` across the affect-anchor migration suite plus the focused memory API write-normalization tests; `py_compile` passed for `server.py` and `scripts/migrate_affect_anchor_sections.py`.
- VPS deploy: `/opt/Ombre-Brain` on `8.136.154.242` fast-forwarded to `73660a9`, rebuilt `ombre-brain` and `ombre-gateway`, and both health checks returned `ok`.
- Live smoke test inside the `ombre-brain` container confirmed the normalized first line is `### moment`.

Prompt/docs guidance was also aligned after the runtime fix:

- `CLAUDE_PROMPT.md` commit on p0: `c4717c2` (`Update Claude prompt grow guidance`), pushed to `origin/feature/memory-diffusion-p0` and `shadow/feature/memory-diffusion-p0`.
- The same prompt change was cherry-picked to `main` as `a969a17` and pushed to `origin/main`.
- The prompt now allows `grow` at day end or when the user sends a long diary/summary, but only after extracting durable events, preferences, commitments, or project state. Whole diaries and raw emotional process should not be sent to `grow` unchanged.
- `shadow/main` was not force-updated because it is not a fast-forward mirror of `origin/main`.

## 2026-06-07 Portrait / Handoff Direction

This section supersedes any older note that treats new-window memory restore as
"inject many recalled memories". The new direction is:

- New windows should restore identity and life context first, not dump a broad
  pile of old memory cards.
- `breath(is_session_start=true)` currently mostly affects new-session dream
  eligibility. Add an explicit handoff shape later, for example
  `breath(mode="handoff")` or `breath(handoff=true)`, so it does not overload
  the dream/session-start flag.
- Handoff mode should return a compact stable block:
  - `Persona`: Haven's current self/persona state and reply posture.
  - `User Portrait`: Xiaoyu's stable profile plus recent state.
  - `Relationship Portrait`: relationship boundaries, milestones, and current
    climate.
  - `Recent Continuity`: the last few days' active projects or emotional
    context.
  - `Optional Anchors`: at most one or two title/summary/path anchors when they
    are essential for orientation.
- Handoff mode should not run broad dynamic recall, related diffusion, random
  resurfacing, or long bucket windows by default.
- Concrete-event lookup remains query-driven. If the new-window user asks
  "why did I cry yesterday" or "the folded-corner thing", use normal
  `breath(query=...)` / Gateway recall to find the specific bucket or moment.

Paw Memory was rechecked from
`C:\Users\86188\AppData\Local\Temp\paw-memory-read`. The part worth borrowing
is the time-depth portrait chain:

```text
daily memory
-> daily summary
-> split into user / persona / relationship observations
-> recent_buffer
-> staging_pool
-> mid_term portrait
-> stable portrait only when significant
```

Adopt this as the next portrait-maintenance shape, with stricter Ombre
guardrails:

- `daily memory`: today's new buckets/moments and optional session summaries.
- `daily summary`: short account of what happened today; not a profile fact.
- `user/persona/relationship split`: separate Xiaoyu facts from Haven
  self-understanding and relationship climate.
- `recent_buffer`: short-term observations, allowed to update automatically.
- `staging_pool`: observations waiting for repetition or significance.
- `mid_term portrait`: recent-weeks understanding, rewritten only from the
  staging pool.
- `stable portrait`: long-term portrait, updated only when the mid-term change
  is significant and evidence-backed.

Important boundary: `assistant_reflection` may inform `persona` or
`relationship` portrait wording, but it is not evidence for Xiaoyu
`profile_fact`. Long-term `profile_fact` still needs evidence and should remain
candidate/confirmed or pass an explicit rule. If future notes conflict with
this section, prefer this section.

## Memory Boundaries

### `pinned` / `protected`

Root settings and non-negotiable continuity. These are not maintained by the LLM automatically.

They can appear in Gateway's Core Memory block when Core Memory injection is enabled.

### Ordinary `permanent`

Long-lived stored memory, but not automatically part of Gateway Core Memory.

Do not treat every `permanent` bucket as root context when building Portrait Memory.

### `profile_fact`

Evidence-bound user portrait facts. These should remain factual, inspectable, and editable.

Each fact must keep an evidence bucket or evidence moment. No evidence means no write.

### `anchor`

Long-term important experiences, relationships, or recurring life facts.

Anchors can help Portrait Memory, but they should still pass the existing age/count/evidence rules. LLM suggestions are allowed later, automatic anchoring is not the first step.

### `persona_state`

Current relationship and affect state from `persona_engine.py`.

This is not the same as user portrait. Keep it separate from `profile_fact`.

### Portrait Memory

A short cached stable-context block compiled from `profile_fact` and selected `anchor` buckets.

First version should be read-only. It should not include ordinary `permanent` buckets, and it should not duplicate `pinned` / `protected` by default.

Next direction: evolve this from a deterministic read-only cache into a
separate Daily Portrait Maintainer. The maintained portrait should have
`user`, `persona`, and `relationship` parts, plus recent/mid-term/stable time
depth. The handoff/new-window path should read this portrait first instead of
starting from broad dynamic recall.

## Work Order

### 1. Write this boundary plan

Done in this document. This gives later code changes one source of truth for scope.

### 2. Add a light Query Planner

Status: implemented as an optional Gateway planner, disabled by default.

Purpose: improve long-message recall without replacing the current recall path.

Trigger only when one of these is true:

- Direct recall has no hit.
- Direct recall confidence is low.
- The current message is clearly multi-topic.
- The query is long enough that one whole-message embedding/keyword search is likely to dilute the useful terms.

The planner calls a small LLM once and requires strict JSON:

```json
{
  "should_search": true,
  "queries": [
    {
      "query": "妈妈电话",
      "must_terms": ["妈妈", "电话"],
      "intent": "find recent related experience",
      "risk": "medium"
    }
  ],
  "too_vague": false
}
```

Rules:

- Keep 1 to 3 short queries.
- Run each short query independently through the existing recall path.
- Do not concatenate the planner queries back into one long sentence.
- Merge candidates in code.
- Multi-query hits get a score bonus.
- Generic-only hits get a penalty.
- A candidate must match at least one `must_terms` item to enter injection consideration.
- Candidates that fail `must_terms` may appear in debug only.
- All kept candidates still pass the current `RecallPolicy`, vague gate, budget, cooldown, and injection rules.

First version should not ask the planner to choose `keep_ids`. Add that only if short-query recall produces too much noise.

### 3. Add planner debug and a small real-query check

Status: implemented in Gateway injection debug.

Debug should show:

- Original query.
- Planner trigger reason.
- Planner JSON.
- Per-query candidates.
- Which candidates were suppressed by `must_terms`.
- Which candidates survived existing policy gates.

Use real examples that previously behaved differently under manual keyword search:

- `妈妈电话`
- `项目 delay 被批评 失眠`
- `团团 花瓶 耳机 回家`
- Other long mixed messages from recent use.

### 4. Optional: add Word Map Lite

Status: implemented as a derived diagnostic index plus private identity alias view. It remains non-injecting.

This borrows the useful part of Paw Memory's word map without importing its whole design.

It is a derived index, not a new memory layer.

Possible tables:

- `memory_word_nodes`
- `memory_word_edges`
- `memory_word_postings`

Possible term sources:

- bucket name
- domain
- tags
- profile kind
- existing content terms
- moment terms if available

Possible edge rules:

- Terms appearing on the same bucket or moment form co-occurrence edges.
- Stop words and overly common words are filtered.
- PMI or document-frequency caps prevent generic terms from dominating.

Use cases:

- Suggest query expansions for planner/debug.
- Surface strong local names or recurring concrete terms.
- Help explain why one candidate was found.

Non-goals:

- Do not replace `memory_edges`.
- Do not treat co-occurrence as evidence.
- Do not inject memories directly because a word edge exists.

### 5. Add read-only Portrait Memory cache

First implementation: done.

Implementation notes:

- Gateway supports `portrait_memory_enabled`, disabled by default.
- Source set is deterministic and read-only: `profile_fact` buckets plus selected `anchor` buckets.
- `pinned`, `protected`, ordinary `permanent`, resolved/digested/deprecated, and ordinary dynamic recall buckets are excluded by default.
- The cache key uses source bucket ids, source `updated_at`, source content hash, and relevant portrait config.
- Cache output is deterministic, not LLM-generated, so unchanged sources reuse the cached block without another model call.
- Portrait Memory is injected in stable system context as a separate `Portrait Memory` block, not inside `Core Memory`.
- Debug payload reports cache hit/miss, source ids, source roles, source hash, token estimate, and version.

First version source set:

- `profile_fact`
- selected `anchor`

Later source candidates:

- selected relationship/weather summaries, only if they do not duplicate `persona_state`

Excluded by default:

- `pinned`
- `protected`
- ordinary `permanent`
- recent dynamic recall

Cache key:

- source bucket ids
- source `updated_at`
- source content hash

If the source key is unchanged, reuse the cached block. Do not resummarize.

Injection:

- Put Portrait Memory in stable system context.
- Keep it separate from `Core Memory`.
- Make it configurable: disabled by default or guarded by a simple interval/config switch.

Debug should show:

- cache hit or miss
- source ids
- source hash
- token estimate
- generated portrait version

Future upgrade: replace or augment this cache with Daily Portrait Maintainer
output. The maintained portrait may be generated by an LLM, but it should
record source bucket ids/session ids, keep user facts separate from Haven
reflection, and expose recent/mid-term/stable layers for inspection.

### 6. Add a Profile Fact page

Status: implemented as a dashboard `Profile Facts` page plus `/api/profile-facts`.

Add a small inspectable page for user portrait facts.

It should show:

- fact text
- kind
- subject / predicate / object
- evidence bucket or moment
- confidence
- last updated time
- source
- active/deprecated state

Actions:

- confirm
- edit
- deprecate
- open evidence

This page is important because user portrait should not become invisible lore.

Current shape:

- Reads existing `profile_fact` buckets and buckets with `profile_kind`.
- Shows parsed `### fact` text, kind, subject / predicate / object, evidence bucket/moment, confidence, source, update time, and active/deprecated state.
- Actions are confirm, edit, deprecate, and open evidence.
- Deprecating sets `active=false`, `deprecated=true`, `resolved=true`, and `digested=true` so stale profile facts stay out of Portrait Memory and ordinary recall.

### 7. Add semi-automatic `profile_fact` proposals

Status: implemented as manual-confirm dashboard proposals from a chosen evidence bucket.

After Portrait Memory is stable, let an LLM propose profile facts.

Proposal JSON must include:

- `fact`
- `profile_kind`
- `subject`
- `predicate`
- `object`
- `evidence_bucket_id` or `evidence_moment_id`
- `confidence`
- `reason`

Rules:

- No evidence means reject.
- First version requires manual confirmation.
- Confirmed facts use the existing `profile_fact` tool/write path.
- Rejected facts stay out of memory.

Current shape:

- Dashboard Profile Facts page accepts an evidence bucket id and optional moment id.
- `/api/profile-fact-proposals` calls the configured dehydration model and returns candidate JSON only.
- Code rejects candidates whose `evidence_bucket_id` does not match, candidates without a fact, invalid moment ids, and duplicates of existing `profile_fact` content.
- `/api/profile-fact-proposals/confirm` writes only one manually confirmed candidate through the existing `profile_fact(...)` path.

### 8. Add semi-automatic `anchor` proposals

After profile proposals behave well, allow suggestions for anchor candidates.

Rules:

- LLM can propose, not directly pin.
- Existing anchor age/count/evidence checks still apply.
- First version requires manual confirmation.
- Anchor candidates should be old or repeatedly important, not just emotionally loud today.

Current shape:

- Dashboard Profile Facts page has a separate Anchor candidate panel.
- `/api/anchor-proposals` calls the configured dehydration model and returns at most one candidate for the given bucket.
- Code rejects candidates whose `bucket_id` does not match, candidates without a reason, profile_fact buckets, feel buckets, and pinned/protected buckets.
- Existing `_can_mark_anchor()` age/count rules are checked before model generation and again through `trace(anchor=1)` on confirm.
- `/api/anchor-proposals/confirm` writes only one manually confirmed candidate through the existing `trace(bucket_id, anchor=1)` path.

### 9. Optional: candidate filter model

If planner recall returns too much noise, add a second lightweight call that sees top candidates and returns:

```json
{
  "keep_ids": ["bucket_id_1", "bucket_id_2"],
  "drop_ids": ["bucket_id_3"],
  "reason": "short explanation for debug"
}
```

Rules:

- It cannot bypass existing policy gates.
- It cannot write memory.
- It cannot inject candidates that the code rejected.

### 10. Optional: internal bucket-id detail recall

The current Gateway already injects short memory summaries with `bucket_id`.
This makes a light two-step recall possible without formal tool calling.

Status on 2026-06-05: implemented as an optional Gateway retry for non-streaming
OpenAI-compatible and Anthropic-compatible requests. It is disabled by default.
Streaming replies do not use this path because the first tokens may already have
been sent to the client.

Shape:

1. First pass injects short summaries and `bucket_id`.
2. If the model sees a relevant summary but needs details, it may put an internal request at the start of its draft:

```text
[memory_detail ids="bucket_id_1,bucket_id_2"]
```

3. Gateway intercepts this line before it reaches the user.
4. Gateway only accepts ids that were already injected in the current turn.
5. Gateway fetches the full bucket or a longer bucket detail block and asks the upstream model again with that temporary context.
6. The final user-visible reply must not contain the internal request.

Why this is preferable to a visible `[recall]` suffix on every user message:

- It does not pollute user messages or chat history.
- It does not make recall feel like part of the user's current wording.
- It avoids always showing a recall instruction to the model.
- It is lighter than formal tool calling because there is no tool schema in every request.
- It works only after Gateway has already found plausible bucket ids.

Guardrails:

- Only one internal detail recall retry per user turn.
- Limit to 2 or 3 bucket ids.
- Do not accept guessed ids.
- Do not write memory.
- Do not store the internal request in conversation history.
- Do not bypass existing recall gates; this only expands details for memories already admitted this turn.

### 11. Add Daily Portrait Maintainer and handoff breath

This is the next preferred work after the section-boundary cleanup. It borrows
Paw's portrait-maintenance mechanism without adopting its fixed recall tail or
fully automatic long-term writes.

Daily maintainer:

1. First run may initialize the portrait from all active buckets, preferably
   using short summaries, paths, tags, created dates, key `### moment` sections,
   and a small amount of clearly-labeled `### reflection`.
2. Later runs only use the day's new memory material plus the previous portrait.
3. The LLM receives a first-person prompt such as: "You are {ai_name}. These are
   today's memories for you and {user_name}. Maintain user/persona/relationship
   portrait observations only from evidence."
4. Output should be patch-like, not an unrestricted rewrite:
   `add_recent`, `move_to_staging`, `rewrite_mid_term`, `stable_candidate`,
   `profile_fact_candidate`, `skip`.
5. Every item must carry evidence bucket/session ids. If the evidence cannot be
   traced, skip.

Suggested storage shape:

```yaml
portrait:
  user:
    recent_buffer: []
    staging_pool: []
    mid_term: ""
    stable: ""
  persona:
    recent_buffer: []
    staging_pool: []
    mid_term: ""
    stable: ""
  relationship:
    recent_buffer: []
    staging_pool: []
    mid_term: ""
    stable: ""
```

Handoff breath:

- Add `breath(mode="handoff")` or equivalent.
- It should inject portrait/persona/personal continuity, not many dynamic
  recalled memories.
- Defaults for handoff should be equivalent to `include_related=false`,
  `include_core=false`, no random resurface, and no broad diffusion.
- Query-specific recall remains separate and explicit.

## First Implementation Slice

The first code slice should be:

1. Query Planner config.
2. Planner prompt and strict JSON parser.
3. Trigger only on low-confidence/no-hit/multi-topic long query.
4. Run 1 to 3 short recall queries independently.
5. Merge, score, and gate with existing policy.
6. Add debug output.

Do not implement the candidate filter model in this first slice.

## Later Implementation Slice

After Query Planner has real-query evidence:

1. Add Portrait Memory read-only cache.
2. Add Profile Fact page.
3. Add manual-confirm profile fact proposals.
4. Add manual-confirm anchor proposals.
5. Use Word Map Lite diagnostics if planner debug shows repeated term-expansion misses.
6. Add Daily Portrait Maintainer.
7. Add handoff-focused `breath(mode="handoff")`.

Items 1 to 7 are now implemented locally; the candidate filter model remains
optional.

## Guardrails

- No automatic `pinned`.
- No automatic `protected`.
- No automatic Core Memory edits.
- No profile fact without evidence.
- No anchor without existing gate checks.
- No planner result bypasses `RecallPolicy`.
- No generic-term-only injection.
- No fixed `[recall]` instruction appended to user messages.
- No internal memory detail request exposed to users or written into history.
- No full L0/L1/L2/L3 memory rewrite.
- No new-window broad memory dump. Handoff should prefer portrait/persona and a
  tiny number of anchors over dynamic recall.

The guiding rule: make the existing memory more legible and better at finding what is already there, before letting it write more about the user.
