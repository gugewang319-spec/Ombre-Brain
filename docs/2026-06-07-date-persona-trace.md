# Date Persona Trace

2026-06-07 working note.

Goal: when the user asks with date words such as `昨天`, `昨晚`, `前天`, or a detail-seeking `今天为什么...`, Gateway may add a small date-specific private trace.

Boundaries:

- Daily impressions and persona events are context temperature, not direct recall seeds.
- Direct memory hits and bucket moments remain the factual source of truth.
- Persona events are used as an index and quality filter.
- The injected date trace prefers short original excerpts from the user turn and assistant reply.
- If old events have no excerpts, fall back to `surface_trigger`, `inner_thought`, and `residue`.
- Date trace bucket ids and persona event ids are visible in debug only; they do not count as injected recall ids and do not open memory detail recall by themselves.

Implementation shape:

- Add short `user_excerpt` and `assistant_excerpt` fields to future `persona_events`.
- Deduplicate repeated same-intent events before daily reflection or date trace injection.
- Select high-quality events by confidence, relationship/personality signal, excerpt presence, and non-generic trigger text.
- For date queries, include up to a few selected turns from the target day plus the matching daily impression when available.
- Keep the block small, read-only, and clearly marked as private date context.
