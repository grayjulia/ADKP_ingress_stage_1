#!/usr/bin/env python3
"""
Verifies the R and Python versions of the ADKP Portal Studies Table tool agree
on the shared constants that must stay in sync: table IDs, column schema
(ALL_COLUMNS/STRING_MAX_SIZE/LIST_COLUMNS/BOOLEAN_COLUMNS/ENTITY_COLUMNS), and
SOP-derived business rules (COLUMN_NOTES, controlled vocabularies, the
ACK_CONTEXT_*/STUDY_METADATA_*/ACCESS_REQS_* reference IDs, deprecated
columns, and the Study_Description length rule).

Deliberately does NOT compare STUDY_ROW/STUDY_UPDATES/DRY_RUN/MODE/
UPDATE_STUDY_ABBREVIATION - those are meant to be edited per use, so a
template and any study-specific copy are expected to differ there.

Needs only the Python standard library and a working `Rscript` with the
lightweight "rjson" package - NOT synapseclient/pandas/synapser - since it
extracts constants without importing/sourcing either file's Synapse-touching
code.

Usage: python3 scripts/check_sync.py
Exit code 0 if in sync, 1 if not (or if either file fails to parse).
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PY_FILE = REPO_ROOT / "portal-studies-table" / "python" / "adkp_studies_table.py"
R_FILE = REPO_ROOT / "portal-studies-table" / "r" / "adkp_studies_table.R"
DUMP_R_SCRIPT = Path(__file__).resolve().parent / "dump_r_constants.R"

KEYS = [
    "STUDIES_TABLE_ID", "PROGRAMS_TABLE_ID", "ALL_COLUMNS", "STRING_MAX_SIZE",
    "STUDY_DESCRIPTION_MAX_SIZE", "DEPRECATED_COLUMNS", "COLUMN_NOTES", "ENUM_VALUES",
    "SPECIMEN_TYPE_VALUES", "SPECIES_VALUES",
    "ACK_CONTEXT_STANDARD", "ACK_CONTEXT_REPROCESSED", "ACK_CONTEXT_UCI_CLU_H2KBKI", "ACK_CONTEXT_VALUES",
    "STUDY_METADATA_STANDARD", "STUDY_METADATA_ADNI", "STUDY_METADATA_ROSMAP",
    "STUDY_METADATA_MAYORNASEQ", "STUDY_METADATA_MSBB", "STUDY_METADATA_VALUES",
    "ACCESS_REQS_CONTROLLED", "ACCESS_REQS_OPEN", "ACCESS_REQS_ADNI", "ACCESS_REQS_FRAMINGHAM", "ACCESS_REQS_VALUES",
    "LIST_COLUMNS", "BOOLEAN_COLUMNS", "ENTITY_COLUMNS",
]

# Only these top-level statements are needed to define every key above - skip
# the heavy/optional imports (synapseclient, pandas) so this check has no
# dependencies beyond the standard library, and stop before the __main__
# block so nothing tries to touch Synapse.
_SKIP_LINE_PREFIXES = ("import synapseclient", "from synapseclient import", "import pandas as pd")


def load_python_constants():
    lines = PY_FILE.read_text().splitlines()
    filtered = [line for line in lines if not line.strip().startswith(_SKIP_LINE_PREFIXES)]
    try:
        cutoff = next(i for i, line in enumerate(filtered) if line.startswith("if __name__"))
        filtered = filtered[:cutoff]
    except StopIteration:
        pass
    namespace = {}
    exec(compile("\n".join(filtered), str(PY_FILE), "exec"), namespace)
    return {key: namespace.get(key) for key in KEYS}


def load_r_constants():
    result = subprocess.run(
        ["Rscript", str(DUMP_R_SCRIPT), str(R_FILE)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def normalize(value):
    """Make dict key order and list/set ordering irrelevant to comparison."""
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, set, tuple)):
        return sorted(normalize(v) for v in value)
    return value


def main():
    try:
        py_constants = load_python_constants()
    except Exception as e:
        print(f"FAILED to load constants from {PY_FILE}: {e}")
        return 1

    try:
        r_constants = load_r_constants()
    except subprocess.CalledProcessError as e:
        print(f"FAILED to load constants from {R_FILE}:\n{e.stderr}")
        return 1

    mismatches = []
    for key in KEYS:
        if normalize(py_constants.get(key)) != normalize(r_constants.get(key)):
            mismatches.append((key, py_constants.get(key), r_constants.get(key)))

    if not mismatches:
        print(f"OK - {len(KEYS)} shared constants match between Python and R.")
        return 0

    print(f"MISMATCH - {len(mismatches)} of {len(KEYS)} shared constants differ:\n")
    for key, py_val, r_val in mismatches:
        print(f"  {key}:")
        print(f"    python: {py_val!r}")
        print(f"    r:      {r_val!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
