# Sample documents (fictional)

Every scheme in this folder is invented. None of them exist, and none of the amounts,
ages, income limits or documents mentioned here describe a real government scheme.
They exist so the pipeline, tests and evaluation harness can run end to end without
downloading anything, and they are labelled "Fictional sample" in the UI.

Ingest them with `scripts\ingest.ps1 -Sample`. Real scheme pages go in `data/raw/`
(either through the scraper or by dropping HTML/PDF files there yourself).

`rules/` holds hand-written, reviewed eligibility rules for these fictional schemes,
and `data/eval/sample_golden.jsonl` holds questions whose answers are in these files.
