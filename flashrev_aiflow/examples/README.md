# flashrev_aiflow · Example fixtures

These files let you dry-run the `aiflow create` pipeline in under a minute.

## Files

| File | Purpose |
|---|---|
| [`contacts.example.csv`](./contacts.example.csv) | 5-row sample CSV with the canonical columns (`name`, `email`, `company`, `title`, `country`). Suitable as the `--csv` argument to `aiflow create`. |
| [`pitch.example.json`](./pitch.example.json) | 6-section pitch scaffold with placeholder copy. Pass to `--pitch-file`. Also contains a top-level `url` field so `--website` is optional. |

## Quick start — dry-run only (no backend writes)

```bash
# From the repo root, relative path to the examples:
flashclaw-cli-plugin-flashrev-aiflow aiflow create --no-wizard --dry-run \
  --csv ./examples/contacts.example.csv \
  --pitch-file ./examples/pitch.example.json \
  --country-column country
```

You should see CSV previewed, pitch validated, mailbox list probed, token
balance reported, and a `Dry-run complete` line at the end. No AIFlow is
created on the backend.

## Produce a fresh pitch scaffold

If you want to author a pitch from scratch rather than copy `pitch.example.json`:

```bash
flashclaw-cli-plugin-flashrev-aiflow aiflow pitch init --out ./my-pitch.json
# then edit ./my-pitch.json and pass --pitch-file ./my-pitch.json
```

The `init` subcommand writes the exact same scaffold that lives in
[`pitch.example.json`](./pitch.example.json), so either path works.
