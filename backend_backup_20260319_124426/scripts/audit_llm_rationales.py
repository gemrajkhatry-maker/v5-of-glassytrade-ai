#!/usr/bin/env python3
"""LLM Rationale Auditing Script.

This script parses the trade journal to evaluate the quality and explainability
of the LLM's rationales. It checks whether the LLM is genuinely considering market
microstructure or if it's falling into a "lazy bias" pattern (e.g., rubber-stamping
the quant signals without referencing specific features).

It looks for:
- Length of rationale (too short = weak explainability).
- Mention of key structural levels (POC, VAH, VAL, LVN, HVN).
- Mention of flow dynamics (CVD, Delta, Volume Bubbles, Aggression).
- Generic phrases that indicate a lack of conviction.
"""

import json
from pathlib import Path

# Important keywords that indicate a mechanically sound rationale
KEY_TERMS = {
    "structure": [
        "poc",
        "vah",
        "val",
        "lvn",
        "hvn",
        "value area",
        "balance",
        "imbalance",
    ],
    "flow": [
        "cvd",
        "delta",
        "bubble",
        "aggression",
        "absorption",
        "stacked",
        "footprint",
    ],
    "setup": ["second drive", "pullback", "reclaim", "fade", "trend"],
}

LAZY_PHRASES = [
    "looks good",
    "seems like",
    "i agree",
    "quant says",
    "going with the signal",
]


def analyze_rationale(rationale: str) -> dict:
    text = rationale.lower()

    # 1. Check length
    word_count = len(text.split())

    # 2. Check keyword hits
    hits = {category: 0 for category in KEY_TERMS}
    for cat, terms in KEY_TERMS.items():
        for term in terms:
            if term in text:
                hits[cat] += text.count(term)

    # 3. Check for lazy phrasing
    lazy_count = sum(1 for phrase in LAZY_PHRASES if phrase in text)

    # Grade the rationale
    score = 10.0
    if word_count < 15:
        score -= 3.0
    if sum(hits.values()) == 0:
        score -= 5.0
    if lazy_count > 0:
        score -= 2.0 * lazy_count

    grade = ""
    if score >= 8.0:
        grade = "Strong (Institutional-grade)"
    elif score >= 5.0:
        grade = "Acceptable (Basic reasoning)"
    else:
        grade = "Weak (Lazy / Generic)"

    return {
        "score": max(0.0, score),
        "grade": grade,
        "word_count": word_count,
        "hits": hits,
        "lazy_count": lazy_count,
    }


def main():
    # Typically, trades are logged in a SQLite DB or JSON lines.
    # For auditing purposes, we assume a local JSON lines fallback file: `data/logs/journal.jsonl`
    # Replace the path as needed to hook into the actual StoragePort implementation.
    journal_path = Path(__file__).parent.parent / "data" / "logs" / "journal.jsonl"

    if not journal_path.exists():
        print(f"Warning: Journal file not found at {journal_path}")
        print(
            "Note: The actual system might use SQLite. This script audits JSONL exports or fallback logs."
        )
        # Provide a sample run for demonstration
        print("\n--- Running on sample rationales ---\n")
        samples = [
            "Market is trending. I will BUY.",
            "Price pulled back to VAH and formed a BUY bubble with strong CVD slope. This is a classic trend continuation setup.",
            "The quant model says LONG, so I agree and recommend LONG. Looks good.",
        ]
        total_score = 0
        for s in samples:
            res = analyze_rationale(s)
            print(f"Rationale: '{s}'\nGrade: {res['grade']} (Score: {res['score']})\n")
            total_score += res["score"]
        print(f"Average Score: {total_score / len(samples):.1f} / 10")
        return

    weak_count = 0
    total_count = 0
    total_score = 0.0

    print(f"Auditing ML Rationales from {journal_path}...")
    with open(journal_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                # Ensure it has a rationale and isn't just a basic tick log
                if (
                    "rationale" in record
                    and record.get("event") == "AIAnalysisCompleted"
                ):
                    total_count += 1
                    res = analyze_rationale(record["rationale"])
                    total_score += res["score"]

                    if res["score"] < 5.0:
                        weak_count += 1
                        print("\n[WEAK RATIONALE DETECTED]")
                        print(f"Time: {record.get('timestamp', 'Unknown')}")
                        print(
                            f"Symbol: {record.get('symbol', 'Unknown')} | Dir: {record.get('direction', 'Unknown')}"
                        )
                        print(f"Text: {record['rationale']}")
                        print(
                            f"Score breakdown: Words={res['word_count']}, Hits={res['hits']}, Lazy Pts={res['lazy_count']}"
                        )

            except json.JSONDecodeError:
                pass

    if total_count > 0:
        print("\n--- Summary ---")
        print(f"Total entries audited : {total_count}")
        print(
            f"Weak/Lazy entries     : {weak_count} ({weak_count/total_count*100:.1f}%)"
        )
        print(f"Average Quality Score : {total_score / total_count:.1f} / 10.0")
        if weak_count / total_count > 0.15:
            print("WARNING: LLM is exhibiting >15% lazy bias. Review prompt context!")
    else:
        print("No AI analysis events found in the journal.")


if __name__ == "__main__":
    main()
