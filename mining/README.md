# Problem mining

Candidate discovery for the four scarce corpora (Strata, PhysLib, CSLib,
ArkLib). Lives outside `competition/` (the teacher's working directory) so
extra theorems are not on the default search path. This is a convention, not
a read restriction.

```
python3 mining/find_problems.py --corpora strata,cslib --dry-run
python3 mining/promote_discovered.py --source strata cslib --min-confidence 5
```

Promoted rows still have to be copied into
`competition/benchmark_data_warmup.jsonl` by hand after review. Corpus clones
stay in `competition/.corpus_cache/` (gitignored).
