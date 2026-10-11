import json
from pathlib import Path

import matplotlib.pyplot as plt

BEFORE_PATH = Path("evidence/task2/quality_before.json")
AFTER_PATH = Path("evidence/task2/quality_after.json")
OUTPUT_PATH = Path("evidence/task2/quality_before_after.png")

before = json.loads(BEFORE_PATH.read_text(encoding="utf-8"))
after = json.loads(AFTER_PATH.read_text(encoding="utf-8"))

before_map = {m["rule_id"]: m for m in before["metrics"]}
after_map = {m["rule_id"]: m for m in after["metrics"]}

shared_rules = [
    "completeness",
    "uniqueness",
    "value_validity",
    "referential_integrity",
    "temporal_consistency",
    "timeliness",
]

display_names = {
    "completeness": "Completeness",
    "uniqueness": "Uniqueness",
    "value_validity": "Value Validity",
    "referential_integrity": "Referential Integrity",
    "temporal_consistency": "Temporal Consistency",
    "timeliness": "Timeliness",
}

labels = [display_names[r] for r in shared_rules]
before_values = [before_map[r]["value"] * 100 for r in shared_rules]
after_values = [after_map[r]["value"] * 100 for r in shared_rules]

x = list(range(len(shared_rules)))
width = 0.36

fig, ax = plt.subplots(figsize=(13, 7))

before_bars = ax.bar(
    [i - width / 2 for i in x],
    before_values,
    width,
    label="Before curation",
)

after_bars = ax.bar(
    [i + width / 2 for i in x],
    after_values,
    width,
    label="After curation",
)

for bar, rule in zip(before_bars, shared_rules):
    m = before_map[rule]
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.15,
        f'{m["value"] * 100:.2f}%\n{m["numerator"]}/{m["denominator"]}',
        ha="center",
        va="bottom",
        fontsize=8,
    )

for bar, rule in zip(after_bars, shared_rules):
    m = after_map[rule]
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.15,
        f'{m["value"] * 100:.2f}%\n{m["numerator"]}/{m["denominator"]}',
        ha="center",
        va="bottom",
        fontsize=8,
    )

ax.set_ylabel("Metric value (%)")
ax.set_title("Data Quality Before vs After Curation")
ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=20, ha="right")
ax.set_ylim(94, 102.5)
ax.legend()
ax.grid(axis="y", alpha=0.25)

qa_text = (
    f'QA Coverage: '
    f'{after_map["qa_coverage"]["value"] * 100:.2f}% '
    f'({after_map["qa_coverage"]["numerator"]}/'
    f'{after_map["qa_coverage"]["denominator"]})'
    "\n"
    f'QA Agreement: '
    f'{after_map["qa_agreement"]["value"] * 100:.2f}% '
    f'({after_map["qa_agreement"]["numerator"]}/'
    f'{after_map["qa_agreement"]["denominator"]})'
)

fig.text(
    0.99,
    0.01,
    qa_text,
    ha="right",
    va="bottom",
    fontsize=9,
)

fig.tight_layout(rect=[0, 0.06, 1, 1])

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUTPUT_PATH, dpi=180, bbox_inches="tight")
plt.close(fig)

print("Generated:", OUTPUT_PATH)
