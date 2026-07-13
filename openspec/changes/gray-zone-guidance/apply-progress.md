# Apply Progress: gray-zone-guidance

**Mode**: Strict TDD  
**Delivery**: auto-chain · stacked-to-main  
**Current slice**: WU2 Consult + VIP freeze (PR2 → main on PR1)  
**Date**: 2026-07-13

## Completed Tasks

### Phase 1 — Foundation (WU1) — 9/9

- [x] 1.1 RED `tests/unit/test_knowledge_store.py`
- [x] 1.2 GREEN `services/knowledge.py`
- [x] 1.3 Wire `training.init_db` / conftest / `diana.py`
- [x] 1.4 RED `tests/unit/test_llm_gap_fields.py` (+ pure)
- [x] 1.5 GREEN config flags
- [x] 1.6 GREEN llm schema+parse+6-tuple
- [x] 1.7 Migrate 6-tuple call sites
- [x] 1.8 Prompt gap doctrine criteria
- [x] 1.9 Full suite green flag-off

### Phase 2 — Consult + VIP freeze (WU2) — 11/11

- [x] 2.1 RED runtime/state tests
- [x] 2.2 GREEN `state.py` pending_guidance + awaiting_guidance_answer
- [x] 2.3 RED `test_guidance_callbacks.py`
- [x] 2.4 GREEN `handlers/callbacks/guidance.py` + register `g:` + router order
- [x] 2.5 RED timer guidance tests (freeze invariants)
- [x] 2.6 GREEN shared `enter_draft_pipeline` (timer) + wire use_draft
- [x] 2.7 GREEN timer gap branch after escalation before save
- [x] 2.8 GREEN reengagement `_has_pending_guidance`
- [x] 2.9 GREEN data_pause/sandbox clear pending; no real consult in sandbox
- [x] 2.10 GREEN owner supersede + recovery re-notify
- [x] 2.11 Freeze suite + full suite green

### Phase 3 — not started (WU3)

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1–1.9 | (WU1 prior) | Unit | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2.1 | `tests/unit/test_guidance_state.py` | Unit | ✅ runtime baseline | ✅ ImportError | ✅ via 2.2 | ✅ 5 cases | ✅ Clean |
| 2.2 | same | Unit | ✅ | ✅ 2.1 first | ✅ 5 passed | ✅ snap/load/active | ✅ Clean |
| 2.3 | `tests/unit/test_guidance_callbacks.py` | Unit | N/A (new) | ✅ Written | ✅ via 2.4 | ✅ answer/skip/use_draft/free-text/exclusion/auth | ✅ Clean |
| 2.4 | guidance.py + router + __init__ | Unit | ✅ | ✅ 2.3 first | ✅ callbacks green | ✅ multi actions | ✅ Clean |
| 2.5 | `tests/unit/test_timer_guidance.py` | Unit | ✅ timer baseline | ✅ Written | ✅ via 2.6–2.7 | ✅ gap/flag/esc/match | ✅ Clean |
| 2.6 | timer `enter_draft_pipeline` | Unit | ✅ | ✅ via use_draft tests | ✅ | ✅ supervised+auto | ✅ Extract helper |
| 2.7 | timer gap branch | Unit | ✅ | ✅ 2.5 first | ✅ | ✅ match skip consult | ✅ Clean |
| 2.8 | `test_guidance_freeze.py` reengage | Unit | ✅ reengage | ✅ Written | ✅ | ✅ block + no-block | ➖ |
| 2.9 | freeze + data_pause clear | Unit | ✅ | ✅ Written | ✅ | ✅ pause clear | ➖ |
| 2.10 | freeze supersede + recovery | Unit | ✅ recovery | ✅ Written | ✅ | ✅ both paths | ✅ Clean |
| 2.11 | full suite | Unit | ✅ | ➖ verify | ✅ **571 passed** | ➖ | ➖ |

### Test Summary

- **WU2 new unit tests**: guidance_state (5) + guidance_callbacks (13) + timer_guidance (5) + freeze (7) ≈ 30
- **Full suite**: **571 passed**, 1 pre-existing RuntimeWarning (unawaited auto_reply in unrelated test)
- **Layers used**: Unit only
- **Approval tests**: None — no pure-refactor-only tasks
- **Pure / shared helpers**: `enter_draft_pipeline`, `open_guidance_consult`, `resolve_guidance_request`, `_has_pending_guidance`

## Files Changed (WU2)

| File | Action | What Was Done |
|------|--------|---------------|
| `state.py` | Modified | `pending_guidance` persist; `awaiting_guidance_answer` runtime-only |
| `handlers/callbacks/guidance.py` | Created | notify, g: handlers, free-text, supersede, open consult |
| `handlers/callbacks/__init__.py` | Modified | Route `g:`; export guidance handlers |
| `handlers/callbacks/approval.py` | Modified | note/fix clear `awaiting_guidance_answer` |
| `handlers/router.py` | Modified | admin_note → guidance → note → correction |
| `handlers/timer.py` | Modified | `enter_draft_pipeline`; gap branch after escalation |
| `handlers/recovery.py` | Modified | Re-notify open guidances on startup |
| `handlers/business.py` | Modified | Owner inbound → supersede guidance |
| `services/knowledge.py` | Modified | `resolve_guidance_request` |
| `services/reengagement.py` | Modified | `_has_pending_guidance` block |
| `services/data_pause.py` | Modified | clear pending_guidance |
| `services/sandbox.py` | Modified | clear pending_guidance on reset |
| `tests/conftest.py` | Modified | `in_memory_training_db` wires knowledge.db |
| `tests/unit/test_guidance_state.py` | Created | Persist/load tests |
| `tests/unit/test_guidance_callbacks.py` | Created | g: + free-text + exclusion |
| `tests/unit/test_timer_guidance.py` | Created | Gap branch + freeze |
| `tests/unit/test_guidance_freeze.py` | Created | Reengage/owner/recovery/sandbox |
| `openspec/.../tasks.md` | Modified | 2.1–2.11 checked |

## Deviations from Design

1. **Free-text answer (WU2 partial)**: Distill+regen deferred to WU3. On free-text, WU2 stores `diana_answer_raw`, marks status `answered`, then re-enters **use_draft-equivalent** path with the original tentative draft so VIP is not left frozen. WU3 will replace this with distill → policy → regen → normal path.
2. **Anti-reask partial**: When `match_policies` non-empty, timer does **not** open consult and falls through to normal save path (no one-shot regen with inject yet — WU3).
3. **Sandbox gap**: When `sandbox`/synthetic examples, gap branch does not open real consult (no production pollution); falls through normal path.

## Issues Found

None blocking. Pre-existing RuntimeWarning about unawaited `auto_reply` still present in suite (unrelated).

## Remaining Tasks

- [ ] Phase 3 WU3 (3.1–3.10) — inject + distill/regen + timeout + admin

## Workload / PR Boundary

- Mode: stacked PR slice (stacked-to-main)
- Current work unit: **WU2 Consult + VIP freeze**
- Branch: `feat/gray-zone-guidance-wu2` (stacked on WU1 tip)
- Boundary: pending_guidance, g: UI, timer freeze, reengage/recovery/owner/sandbox; free-text capture without distill
- Out of scope this PR: policy inject, distill LLM, timeout worker, `/politicas`, full anti-reask regen
- Estimated review budget impact: medium–high but autonomous WU2 slice

## Status

**WU1 9/9 + WU2 11/11 complete.** Ready for next batch: `sdd-apply` WU3.
