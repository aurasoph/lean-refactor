# Version projects

Each sibling directory is a major-version workspace. Problem files are duplicated across every applicable version, as required by the benchmark's cross-toolchain evaluation model.

Corpus libraries are declared as git dependencies in each `lakefile.toml` (not checked out under `sources/`). The exact version-to-commit matrix is authoritative in the `version_info` field of `../benchmark_data_warmup.jsonl`. Do not infer a commit from the directory name when preparing a submission.
