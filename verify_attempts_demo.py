import sys
import json
from backend.database import SessionLocal
import backend.models as models

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

db = SessionLocal()

cards = db.query(models.ReasoningCard).all()
print("=" * 65)
print(f" TOTAL REASONING CARDS IN DATABASE: {len(cards)}")
print("=" * 65)

attempt_lengths = {}
sample_by_step = {}

for c in cards:
    bd = json.loads(c.calculation_breakdown) if isinstance(c.calculation_breakdown, str) else c.calculation_breakdown
    attempts = bd.get("attempts_tried", [])
    n = len(attempts)
    attempt_lengths[n] = attempt_lengths.get(n, 0) + 1
    if n not in sample_by_step and attempts:
        sample_by_step[n] = {
            "category": c.suggested_category.value if hasattr(c.suggested_category, "value") else str(c.suggested_category),
            "attempts": attempts
        }

print("\nDISTRIBUTION OF HYPOTHESIS EVALUATION DEPTH (200 Exceptions):")
for depth in sorted(attempt_lengths.keys()):
    print(f"  • {attempt_lengths[depth]:>2} exceptions resolved at search depth {depth}")

print("\nSAMPLE TRAJECTORIES ACROSS DIFFERENT EVALUATION DEPTHS:")
for depth in sorted(sample_by_step.keys())[:4]:
    info = sample_by_step[depth]
    print(f"\n--- Search Depth {depth} (Result Category: {info['category']}) ---")
    for step in info["attempts"]:
        print(f"    [Step] {step}")

db.close()
