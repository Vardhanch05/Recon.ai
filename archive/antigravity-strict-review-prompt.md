# Prompt for Antigravity — Strict Pre-Implementation Review

Paste everything below as your instruction to Antigravity. Attach/reference all 19 files in `/docs` when you do.

---

## Context

I'm building a **Multi-Source Settlement Reconciler** for Track 4 (AI Finance Controller) of the Razorpay AI Builder Buildathon. The track's bar: *"Build an agent that closes one finance-ops loop across a 50+ record batch of synthetic data, reporting its match rate and the exceptions it could not resolve. Throughput plus measured accuracy plus an honest exception list. One cherry-picked match proves nothing."*

The docs in `/docs` were produced with the help of another AI tool (Kiro) across multiple passes and file types (PRD, TRD, technical design, backend schema, API spec, UI/UX brief, implementation plan, app flow, HLD diagram, audit notes, bug list, testing notes, task tracker, README, agent instructions). Two files — `track4-reconciler-lld.md` and `master-prompt-track4-reconciler.md` — are the most recently hardened source of truth after several rounds of independent review; `track4-review-actionable.md` and `track4-review-actionable-addendum.md` are the review history that produced that hardened state.

**I have not yet started implementation.** This review happens before any code is written. Do not write code as part of this task — output findings only.

---

## Why this review matters (read before starting)

Every prior review pass on this project has found real, load-bearing bugs — not style nits. Examples from the review history, to calibrate how deep to dig:

- A matching-fallback condition compared gross billed amount to net settled amount directly, which would silently match ~0% of fee-deducted records while claiming an 80% match-rate demo number.
- A timestamp tolerance of ±2 seconds was used to fall back-match records against a settlement cycle that is T+2 (2 business days) — mathematically guaranteed to reject every candidate.
- A fix to one matching path (order_id) introduced a `routing_reason` ENUM value (`amount_match`) in the pseudocode that was never added to the actual database ENUM definition — meaning the fix as written would throw a constraint violation on insert.
- A priority tracking table referenced item numbers that didn't match the numbered headings in the same document.
- A validation function referenced a constant (`RESOLVED_THRESHOLD`) that was never defined anywhere in the file.

**The pattern across all of these:** the bug is never in the obviously-hard part (the LLM reasoning logic). It's always in the boring connective tissue — a value used in pseudocode that doesn't exist in the schema, a status your API returns that your ENUM doesn't accept, a field one doc assumes exists that another doc never defines, a threshold that's referenced in three places and stated differently in each. **With 19 files now instead of 2, the number of places for this kind of drift to hide has grown substantially. That is the primary risk this review needs to catch.**

---

## What "strict" means for this review

- Read every file completely. Do not summarize from filenames or skim.
- Do not soften findings to be encouraging. If something is broken, say it's broken and say exactly where.
- Do not accept a design decision as sound just because it's written confidently or because multiple docs repeat it — repetition across files is not verification.
- Flag anything you cannot verify against another document in the set as unverified, not as correct-by-default.
- If a claim in these docs is presented as a validated fact (market research, competitor gap analysis, cost estimates, latency numbers) but no source or calculation is shown, flag it as an unverified assumption rather than treating it as established.
- Do not silently "fix" anything in your head and move on — if you notice an inconsistency, it goes in the findings, even if you're fairly sure what the intended resolution is.

---

## Specific things to check, in order

### 1. Internal consistency of the newer strategy/spec docs
Read `PRD.md`, `TRD.md`, `technical-design.md`, `implementation-plan.md`, `research.md`, `app-flow.md`, `ui-ux-brief.md`, `backend-schema.md`, `api.md` against each other. For each pair of documents that describes the same thing (e.g., a data model, an endpoint, a pipeline stage, a status value), check:
- Do they name the same fields/tables/statuses the same way?
- Do enum value lists match exactly, everywhere they appear (schema doc vs. API doc vs. technical design doc vs. any pseudocode)?
- Do request/response shapes described in `api.md` match what `backend-schema.md` says the database actually stores?
- Does `app-flow.md`'s described user journey match what `ui-ux-brief.md` describes as the UI, and what `api.md` exposes as callable endpoints to support that journey?
- Do any two documents describe the same matching/reconciliation logic differently (e.g., different tolerance values, different fallback conditions, different confidence formulas)?

### 2. Consistency against the hardened LLD baseline
Treat `track4-reconciler-lld.md` and `master-prompt-track4-reconciler.md` as the most recently corrected version of the design. For every other document that also describes matching logic, the confidence-scoring formula, the API surface, the database schema, or the LLM reasoning/tool-calling flow — check whether it reflects the **current, fixed** version of that logic, or an **earlier, already-disproven** version. Specifically verify each of these fixes is reflected consistently everywhere the underlying concept appears, not just in the LLD:
- The order_id match path does not require `fee_deducted` to be present to count as a match; fee-adjusted amount is a sanity check only, not a match gate.
- The fallback (non-order_id) match path's timestamp tolerance assumption is stated explicitly (transaction timestamp vs. credit-posting timestamp) everywhere the fallback is described.
- `calculate_difference` (or whatever any given doc calls the arithmetic tool) supports refund and FX adjustment parameters, not just a single fee percentage and flat surcharge — check every doc that shows this tool's signature or an example call.
- Confidence score is always described as derived from `residual_gap`, never as something the LLM self-reports, in every doc that touches on it.
- The `reconciliation_results` status/enum values are consistent everywhere: matched_deterministic, matched_ai_resolved, exception_unresolved, human_approved, human_rejected — plus the `routing_reason` enum, which must include success-path values (order_id_match, amount_match) in addition to exception-path values (amount_mismatch, no_match, ambiguous_multiple, currency_mismatch). Check `backend-schema.md`, `api.md`, and any pseudocode in `technical-design.md`/`TRD.md` for whether they've actually applied the `amount_match` addition, since that gap was only caught in the LLD in the most recent pass and may not have propagated to the newer docs.
- The approve/reject concurrency guard (atomic `WHERE status = 'pending'` update, 409 on conflict) is described identically for both endpoints wherever the API is documented.

### 3. New-document-specific checks
- **`backend-schema.md`**: does every table/column/enum here match `track4-reconciler-lld.md` §3 exactly? List every discrepancy, however small (column name casing, type, nullability, missing constraint).
- **`api.md`**: does every endpoint match `track4-reconciler-lld.md` §6? Check request/response schemas field-by-field, not just endpoint names. Check that every status code path (200, 409, etc.) mentioned in the LLD is also present here.
- **`HLD_diagram.png`**: does the high-level architecture in the image match the component breakdown and data flow described in `technical-design.md`, `TRD.md`, and the LLD's §1–2? Note any component present in one but missing in another, and any direction-of-data-flow mismatches.
- **`implementation-plan.md`**: does the build order here match LLD §12? If it differs, is the difference intentional and justified, or does it re-introduce the "build the risky parts last" problem the LLD's build order was specifically designed to avoid?
- **`bugs.md`**: cross-check every bug listed here against the fixes already documented in `track4-review-actionable.md` and `track4-review-actionable-addendum.md`. Flag: (a) any bug marked resolved in `bugs.md` that isn't actually reflected in `backend-schema.md`/`api.md`, and (b) any bug from the actionable/addendum docs that isn't tracked in `bugs.md` at all.
- **`TESTING.md`**: do the described test cases actually exercise the specific edge cases the review history flagged (fee_deducted null on order_id path, ambiguous_multiple with multiple candidates, concurrent approve/reject, timestamp tolerance boundary, combined-cause hypothesis, deliberately unresolvable record)? List which of these are covered and which are not.
- **`audit.md`**: does the event_type enum and logging scope here match `audit_log` in `backend-schema.md`/LLD §3.5?
- **`task_today.md`**: is this consistent with `implementation-plan.md`'s stated build order, or does it contradict it (e.g., starting with a component the plan says should come later)?
- **`AGENTS.md`**: if this file gives instructions to an AI coding agent (naming conventions, file structure rules, tool constraints), check whether anything in it would conflict with the LLD's design — for example, an instruction that would push the agent toward a database schema or API shape that doesn't match `backend-schema.md`/`api.md`.
- **`README.md`**: check that setup instructions, tech stack description, and stated project scope match the LLD and PRD. Flag anything aspirational that isn't actually in scope per the other docs.

### 4. Numeric and threshold consistency
List every numeric threshold, percentage, or timing value that appears in more than one document (e.g., match rate targets, confidence band boundaries, timestamp tolerance seconds, throughput targets, dataset record-count splits). For each one, state every value found and every document it came from, and flag any mismatch explicitly — even a mismatch you suspect is just a typo.

### 5. Fabrication check
For any claim of external validation (market research, "confirmed pain point," competitor feature gaps, cost/pricing figures, cited statistics) in `research.md`, `PRD.md`, or elsewhere: state whether the document shows its work (a source, a calculation, a stated assumption) or simply asserts the claim. Flag unsourced assertions clearly as unverified — do not treat confident phrasing as evidence.

---

## Output format required

Structure your findings exactly like this, reusing the numbering style already established in `track4-review-actionable.md` (continue numbering from where that file left off — it ends at item 17; start new findings at 18):

```
## ✅ WHAT'S CONSISTENT / GOOD (confirmed across all relevant docs)
[only include items you actually cross-checked against 2+ documents]

## ❌ WHAT'S BROKEN (contradicts the hardened LLD baseline, or breaks internally)
### [N]. [short title]
**Location:** [file(s) + section]
**Problem:** [exact quote or precise paraphrase from each conflicting doc]
**Fix:** [concrete, specific — not "align these documents," but what the correct value/wording should be]

## ⚠️ GAPS (missing, not contradictory)
[same format]

## ❓ UNVERIFIED CLAIMS
[claims with no shown source/work — list document + claim, no fix needed, just flag]

## 📋 PRIORITY TABLE
| Priority | Item | Effort | Risk if skipped |
```

Do not skip the priority table. Do not produce a purely narrative summary — every finding needs a location, and every P0/P1 finding needs a concrete fix, not just a description of the problem.

---

## Explicit non-goals for this pass

- Do not re-litigate the LangGraph/LangChain decision already finalized in `master-prompt-track4-reconciler.md`.
- Do not propose new features or scope expansions — this is a consistency and correctness audit, not a brainstorm.
- Do not rewrite entire documents. Point at exact locations and exact fixes.
