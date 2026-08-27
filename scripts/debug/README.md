# Debug scripts

One-off investigation scripts, mostly from tracing skin id `1029303` through the
game's PAK and locres files.

These are **not tests**. They lived in `tests/` and one of them —
`test_patch_extraction.py` — matched pytest's `test_*.py` pattern while doing its
work at import time, so `pytest tests/` aborted during collection and the entire
backend suite failed to run. They were moved here so the test tree contains only
tests.

Each script expects a configured Marvel Rivals install (`SETTINGS.marvel_rivals_root`)
and is run directly:

```
python -m scripts.debug.list_all_paks
```
