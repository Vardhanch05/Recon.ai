# Track 4 Reconciler — Review Addendum (New Findings)

This addendum supplements `track4-review-actionable.md`. It does not replace that document — items 1–15 there still stand. These are gaps found on a second pass, including corrections to the original priority table itself.

---

## ❌ NEW / UPGRADED ISSUES

### 16. Timestamp fallback tolerance contradicts the T+2 settlement cycle
**Location:** §4.1 matching algorithm, tolerance window note

**Problem:** The fallback match compares `order_timestamp` to `settlement_timestamp` with a **±2 second** tolerance. But the project's own problem framing states settlements land on a **T+2 (2 business day)** cycle. An order placed Monday and settled Wednesday will never be within 2 seconds of its own order timestamp. Even after fixing the amount-comparison bug (original item #1), the fallback path will still match close to zero records, because the timestamp gate rejects everything first.

**This is the same root cause as original item #1** — both are "the fallback match condition doesn't reflect how settlement actually works" — and should be fixed together, not treated as two separate bugs.

**Fix — pick one and document the choice:**
- Clarify what `settlement_timestamp` actually represents. If it's the original transaction timestamp echoed back in the settlement file (common in real gateway reports), a ±2 second window makes sense and the field name/description should say so explicitly.
- If `settlement_timestamp` is genuinely the credit-posting time, widen the tolerance window to reflect the settlement cycle (e.g., a multi-day window, or drop timestamp from the fallback entirely and rely on amount + order metadata only).
- Whichever you pick, add one sentence to §4.1 stating the assumption so a judge question doesn't surface it live.

**Status:** Not present in the original actionable doc. Treat as equal priority to original item #1 (they share a fix).

---

### 17. Approve/reject concurrency guard is asymmetric
**Location:** §6 API — `/reconciliation/{result_id}/approve` and `/reconciliation/{result_id}/reject`

**Problem:** Original item #3 specifies an atomic `WHERE status = 'pending'` guard, but only for `/approve`. Nothing in the doc applies the same guard to `/reject`, and there's no stated handling for the cross-case race — an approve and a reject firing near-simultaneously on the same card.

**Fix:** Apply the identical conditional-update pattern to `/reject`:
```sql
UPDATE reconciliation_results
SET status = 'human_rejected', reviewed_at = NOW(), reviewed_by = :user_id
WHERE id = :result_id AND status = 'pending'
```
If `rowcount == 0` for either endpoint, return 409 regardless of which action arrived second. Document this as one shared idempotency rule covering both endpoints, not a rule that lives only on `/approve`.

---

## 🔧 CORRECTIONS TO THE ORIGINAL ACTIONABLE DOCUMENT

### 18. Priority table mislabels "item 2" twice
**Location:** `track4-review-actionable.md`, priority table

**Problem:** The P0 row "Fix fallback match condition" cites **(item 2)**, but the fallback match bug is written up in the body as **item 1**. "Item 2" is separately and correctly used later in the same table for the `calculate_difference` tool-signature fix. The label is a copy-paste error and makes the table ambiguous if used as a standalone checklist.

**Fix:** Change the P0 row's label from `(item 2)` to `(item 1)`.

### 19. Item #8 is missing from the priority table
**Location:** `track4-review-actionable.md`, priority table

**Problem:** Item #8 (`reconciliation_results` can have both FKs null — missing `CHECK` constraint) is fully written up in the body but never appears in the priority table. Every other numbered item (6, 7, 9–15) is represented; #8 is the one omission. Anyone working strictly from the table will silently skip it.

**Fix:** Add a row:

| Priority | Item | Effort | Risk if skipped |
|---|---|---|---|
| P2 | Add `CHECK` constraint / NOT NULL on `reconciliation_results` FKs (item 8) | 10–15 min | Orphaned result rows with no parent record possible |

### 20. Item #14's priority and framing undersell the bug
**Location:** `track4-review-actionable.md`, item 14 write-up and priority table

**Problem:** Item #14 is filed as P3, "Minor inconsistency in design," and frames the issue purely as "the tolerance value has nowhere to live in the schema." That's true, but it skips the more important question: whether ±2 seconds is a sane tolerance value at all — see item #16 in this addendum. As written, item #14 could be "fixed" (add the config column, expose the param) while the underlying matching bug remains completely broken.

**Fix:** Re-scope item #14 to explicitly reference item #16, and move it to P0/P1 alongside the fallback-match fix rather than P3.

---

## 📋 UPDATED PRIORITY ADDITIONS

| Priority | Item | Effort | Risk if skipped |
|---|---|---|---|
| P0 | Fix timestamp tolerance vs. T+2 settlement cycle (item 16) — pair with original item 1 | 30–45 min | Fallback match still returns ~0 results even after amount-comparison fix |
| P1 | Apply concurrency guard symmetrically to `/reject` (item 17) | 15 min | Race condition on reject path mirrors the approve-path bug the original review caught |
| P2 | Add missing `CHECK` constraint row for item 8 to tracking table | 10–15 min | Orphaned rows possible; was silently dropped from original priority table |
| — | Correct "(item 2)" mislabel on fallback-match row in original table | 1 min | Table ambiguity if used as a work checklist |
| — | Re-file original item 14 as P0/P1, tied to item 16 | — | Currently mis-prioritized as cosmetic |

---

## Net effect on original priority table

The original P0 row list should read:

1. Fix fallback match condition **+** timestamp tolerance together (items 1 + 16) — 45–60 min combined
2. Add concurrency guard to **both** approve and reject (items 3 + 17) — 30 min combined
3. Fix reject path ENUM + status (item 4) — 30 min

Everything else in the original P1–P3 tiers stands as written, with the addition of item 8's row and the correction to item 14's priority.
