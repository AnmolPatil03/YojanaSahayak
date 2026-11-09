# Evaluation report (2026-11-09T08:03:57+00:00)

- Corpus: sample (23 chunks)
- Golden file: `sample_golden.jsonl` with 17 verified questions (13 answerable, 4 unanswerable)

## Retrieval

| Configuration | recall@1 | recall@3 | recall@5 | recall@10 | mrr | ndcg@5 |
|---|---|---|---|---|---|---|
| Dense only | skipped | skipped | skipped | skipped | skipped | skipped |
| BM25 only | 0.231 | 0.308 | 0.615 | 0.615 | 0.339 | 0.392 |
| Hybrid (RRF) | skipped | skipped | skipped | skipped | skipped | skipped |
| Hybrid + rerank | skipped | skipped | skipped | skipped | skipped | skipped |
| Hybrid + rerank + contextual headers | skipped | skipped | skipped | skipped | skipped | skipped |
| Configured pipeline (retrieval.yaml) | skipped | skipped | skipped | skipped | skipped | skipped |

- Dense only skipped: no dense index (run ingestion with the embedding model available)
- Hybrid (RRF) skipped: no dense index (run ingestion with the embedding model available)
- Hybrid + rerank skipped: no dense index (run ingestion with the embedding model available)
- Hybrid + rerank + contextual headers skipped: no dense index (run ingestion with the embedding model available)
- Configured pipeline (retrieval.yaml) skipped: no dense index (run ingestion with the embedding model available)

## Answers

Skipped: not requested

## Abstention threshold

Not computed.

## Notes

- Abstention sweep skipped: no dense index (run ingestion with the embedding model available)
- This example was produced on a machine without PyTorch, access to the Hugging Face model hub or LLM API keys, so only the BM25 run could execute. Run scripts\eval.ps1 -Sample on your machine for the dense, hybrid and reranked runs and the answer-quality metrics.
