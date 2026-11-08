# Job analyzer evaluation cases

`tasks.json` contains synthetic edge cases for manually evaluating analysis
quality. It is not a benchmark and does not contain real job postings.

Check that the analyzer:

- Quotes salary and experience only when present in the supplied text.
- Does not confuse revenue targets, stipends, or other numbers with salary.
- Keeps required skills distinct from preferred or nice-to-have skills.
- Does not invent requirements when the posting is vague or silent.
- Highlights exact phrases on the page and handles paste-only input without
  claiming it highlighted the page.
- Reports ambiguous or contradictory requirements without resolving them by
  guessing.

Results: **Not run.** Review model output manually; the model's summary is not
a substitute for reading the original posting.
