# First real scans (Task 16)

## Pilot: run 1 (`scan --max-videos 100 --budget 2`)

- Completed in 4 min 44 s for **$0.67** (jev $0.02 · llm $0.36 · scrapecreators $0.29), no failed items.
- Funnel: 100 collected → 100 passed filter → 46 signals → 29 trends proposed → 0 kept.
- Every trend was pruned for support < 3: the prompt's fixed "20–60 trends" made the LLM split 46 signal videos into
  29 trends of 1–2 videos each.
- Transcripts available for 77% of videos; "none of these" rate 2%.

**Changes made after the pilot** (each test-first; user-directed or user-approved):
- Budget guard trims briefs before comments (user: "lower the number of briefs instead, keep the most important ones only").
- Discover asks for about one trend per 6 signal videos, capped at 60 (no change at full scale).
- Cost projection uses the observed 100% filter pass rate; `--estimate` prints the guard's planned trims.

## Full scan: run 2 (defaults: 1,000 videos, 30 days, $5 cap)

- **Duration:** 8 min 21 s, then stopped by an OpenRouter HTTP 520 at judge (986 of 992 videos judged); resumed after
  making every 5xx retryable (test-first), and the resume took 5 min 4 s. **Total ≈ 13.5 min.**
- **Cost:** **$4.19** (jev $0.26 · llm $1.81 · scrapecreators $2.12). The resume paid for nothing twice.
- **Funnel:** 1,000 collected → 992 passed filter → 431 signals → 60 trends proposed → 49 kept → 14 briefs
  (budget guard: 14 briefs instead of 20; comments kept for the 150 most-commented videos).
- **Diagnostics:** "none of these" rate 19%; no self-check flags; 623 borderline videos; 343 videos (35%) without a
  transcript; no failed items.
- **Top trends:** US health insurance deductibles and denials (0.79); grocery-haul-to-meal-prep budgeting (0.69);
  monthly bulk grocery hauls against inflation (0.68); buy-now-pay-later for bills and essentials (0.64); corporate
  disillusionment and quiet boundaries (0.63); spreadsheet budget trackers over budgeting apps (0.63).

## Success criteria (spec §2.3)

1. **Under $5 and 30 minutes:** met ($4.19, about 13.5 minutes including the resume).
2. **Precision/recall on labels:** pending. Run `scripts/scan.sh label 2` in a terminal, then `scripts/scan.sh eval 2`.
3. **5–15 signals worth a closer look:** pending the user's read of `reports/2026-09-29-scan-2.md`.

## Threshold changes

None yet; decide after the evaluation. New thresholds apply to future scans (reports keep each run's settings).
