# ADKP_ingress_stage_1

Reusable tooling for entering and updating rows in the ADKP Portal Studies
Table ([syn17083367](https://www.synapse.org/Synapse:syn17083367/tables/)),
which drives the study detail pages on the AD Knowledge Portal.

## Layout

Code is grouped by tool first, then by language, since the Python and R
versions are meant to be equivalent implementations of the same tool kept in
sync with each other (see below) rather than independent projects:

```
portal-studies-table/
  python/adkp_studies_table.py
  r/adkp_studies_table.R
```

Future tools for other ingress stages/tables can follow the same pattern
(`<tool-name>/python/`, `<tool-name>/r/`) alongside `portal-studies-table/`.

## Using a script

Each file is a standalone, edit-and-run script:

1. Open the language version you want and edit the `STUDY_ROW`/`STUDY_UPDATES`
   and `DRY_RUN`/`MODE` values near the top (see the "SOP REFERENCE" section
   above them for what each field means and its valid values).
2. Run it. It always prints a validation report against the SOP's business
   rules and the live table; it only writes to Synapse if `DRY_RUN` is
   `False`/`FALSE` and there are no `ERROR`-level issues.

See the docstring/header comment at the top of each file for setup details
(package installation, Synapse authentication).

## Keeping the Python and R versions in sync

Both files independently encode the same schema and SOP business rules
(column names/limits, controlled vocabularies, deprecated columns, the
`ACK_CONTEXT_*`/`STUDY_METADATA_*`/`ACCESS_REQS_*` reference IDs, etc.). If
one is edited without the other, they can silently drift apart.

`scripts/check_sync.py` guards against that: it extracts the shared constants
from both files (without needing `synapseclient`/`pandas`/`synapser`
installed) and fails if any differ. It deliberately ignores `STUDY_ROW`,
`STUDY_UPDATES`, `DRY_RUN`, `MODE`, and `UPDATE_STUDY_ABBREVIATION`, since
those are meant to be edited per use.

Run it locally with:

```bash
python3 scripts/check_sync.py
```

It also runs automatically in CI (`.github/workflows/check-sync.yml`) on any
push or PR that touches `portal-studies-table/` or `scripts/`.

**When you change a shared constant (a column's max length, a controlled
vocabulary, the SOP guidance text, a reference ID, etc.), update it in both
`adkp_studies_table.py` and `adkp_studies_table.R`, then run the sync check
before committing.**
