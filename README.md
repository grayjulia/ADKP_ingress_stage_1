# ADKP_ingress_stage_1

Tooling for ADKP data ingress, stage 1.

## Layout

Code is grouped by tool first, then by language (for tools with equivalent
implementations in more than one language, kept in sync with each other -
see each tool's own section below for details):

```
<tool-name>/
  python/...
  r/...
```

## Tools

### Data Ingress

Reusable tooling for auditing a study's Synapse folder tree and permissions,
safely creating/renaming/moving/removing staging folders, and uploading
contributor files with checksum verification and provenance - for any ADKP
data ingress ticket (ADEL-806 is the first use case, but it's not hardcoded
to that ticket or to any particular folder arrangement).

```
data-ingress/
  python/folder_setup.py
  python/requirements.txt
```

#### Using the script

1. `pip install -r data-ingress/python/requirements.txt`
2. Authenticate via `synapse config` (~/.synapseConfig) or the
   `SYNAPSE_AUTH_TOKEN` env var - never hardcode credentials in the script.
3. Edit the `CONFIG` dict near the top of `folder_setup.py` (ticket ID,
   root Synapse ID, and - once known - `folder_plan`/`upload_plan`). Leave
   `folder_plan`/`upload_plan` empty to run in audit-only mode.
4. Run it (`python folder_setup.py`). It always prints the current
   folder tree, a permission audit, and a storage-location check; it only
   writes to Synapse if `CONFIG["dry_run"]` is `False` and there are no
   `ERROR`-level issues.

See the module docstring and the `SOP_NOTES` dict at the top of the file for
the SOP/security reasoning behind each check (private-folder enforcement,
HTTPS assertion, the `scicomp`-only rule for any external AWS storage
location). Different portals/programs structure their Synapse folders very
differently (ADKP nested Staging/Data, ELITE flattened, GENIE
Test/Staging/Production projects, versioned `vN_ingest` folders elsewhere) -
this script never assumes a particular shape, it audits whatever tree
actually exists under the configured root and only changes what
`folder_plan` explicitly declares.

### Synapse Wiki

Reusable tooling for creating and updating Synapse Wiki pages (root pages and
sub-pages) - e.g. a study's main wiki, its Methods sub-page, or an
Acknowledgement sub-page - while preserving contributor-submitted HTML
formatting (links, superscript, subscript, etc.) exactly as written. Includes
an optional helper to pull a contributor's text straight from a Jira ticket
field as Jira's own rendered HTML, avoiding a manual copy/paste step.

```
synapse-wiki/
  python/adkp_wiki_template.py
  python/requirements.txt
```

#### Using the script

This one is meant to be imported, not edited-and-run (owner/title/content
vary per call, unlike the single-row scripts above):

```python
from adkp_wiki_template import login, create_or_update_wiki

syn = login()

# Preview first: opens the content file in your browser and prints the
# create/update plan: writes nothing to Synapse.
create_or_update_wiki(
    syn, owner_id="syn...", title="...", content_path="content.html",
    parent_id=None,  # only used when creating a brand-new page
    dry_run=True,
)

# Looks right -> push for real.
create_or_update_wiki(syn, owner_id="syn...", title="...", content_path="content.html")
```

It also works from the command line (`python adkp_wiki_template.py --help`),
and as a standalone Jira-to-Synapse pull via `fetch_jira_rendered_fields()` /
`save_jira_field()` for teams with a Jira API token. See the module
docstring for full details, including why content is always passed as a
**file path** rather than an inline string (the only mode that preserves the
contributor's HTML byte-for-byte), and the fallback import paths (browser
DevTools copy, Word/Google Docs round-trip) for when Jira API access isn't
available.

### Portal Studies Table

Reusable tooling for entering and updating rows in the ADKP Portal Studies
Table ([syn17083367](https://www.synapse.org/Synapse:syn17083367/tables/)),
which drives the study detail pages on the AD Knowledge Portal.

```
portal-studies-table/
  python/adkp_studies_table.py
  r/adkp_studies_table.R
```

#### Using a script

Each file is a standalone, edit-and-run script:

1. Open the language version you want and edit the `STUDY_ROW`/`STUDY_UPDATES`
   and `DRY_RUN`/`MODE` values near the top (see the "SOP REFERENCE" section
   above them for what each field means and its valid values).
2. Run it. It always prints a validation report against the SOP's business
   rules and the live table; it only writes to Synapse if `DRY_RUN` is
   `False`/`FALSE` and there are no `ERROR`-level issues.

See the docstring/header comment at the top of each file for setup details
(package installation, Synapse authentication).

#### Keeping the Python and R versions in sync

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
