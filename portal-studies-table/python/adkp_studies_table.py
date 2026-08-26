"""
Reusable helpers for adding and updating rows in the ADKP Portal Studies table
(syn17083367 - https://www.synapse.org/Synapse:syn17083367/tables/).

Schema constants (column names/types/sizes) were pulled live from Synapse's
table schema on 2026-08-26 via GET /entity/syn17083367/column. Business rules
(controlled vocabularies, formatting conventions, deprecated columns) come from
the SOP "Add or Update Portal Study Tables (ELITE and ADKP Portals)" v2.1
(Confluence AD space, page 4566515713), section 5.1.2, fetched 2026-08-26.
Re-check that page if this table's conventions seem to have changed - it is
the source of truth for *why* a value is entered a certain way, while the
Synapse column API is the source of truth for what the table will *accept*.

Setup:
    pip install synapseclient pandas
    Authenticate once via `synapse config` (~/.synapseConfig) or by setting the
    SYNAPSE_AUTH_TOKEN env var to a personal access token - do not hardcode
    credentials in this file.

To use: edit STUDY_ROW and DRY_RUN below, then run this file directly
(`python adkp_studies_table.py`). It will always print a validation report;
it only submits to Synapse if DRY_RUN is False and there are no ERROR-level
issues.

Caveat: STRING_LIST columns (Program, DataType_All, specimenType, studyFocus,
Data_Contributor, Species, "Grant Number") are passed here as plain Python
lists in the DataFrame cells, which is how recent synapseclient (>=2.6)
versions expect list-column values. If you're on an older client and storing
fails or silently mis-encodes, check synapseclient's release notes for how
your version wants list columns represented.
"""

import re

import pandas as pd
import synapseclient
from synapseclient import Table

# ==============================================================================
# SOP REFERENCE - read this before filling in STUDY_ROW below. Condensed from
# section 5.1.2 of the SOP "Add or Update Portal Study Tables (ELITE and ADKP
# Portals)" v2.1 (Confluence AD space, page 4566515713), fetched 2026-08-26.
# ==============================================================================

# Columns the SOP says are deprecated - do not populate.
DEPRECATED_COLUMNS = {
    "Citations": "Deprecated - leave blank. A publications scraper (GitHub Action) "
                 "maintains citation data separately; do not manually enter it.",
}

# Per-column guidance condensed from SOP section 5.1.2, keyed by column name.
COLUMN_NOTES = {
    "Study_Type": "Almost all studies are 'Individual'. 'Consortium' is reserved for "
                  "cross-consortium efforts (e.g. reprocessing studies) - verify with the business owner.",
    "Program": "Multiple allowed. Must match the current values in the ADKP Programs table "
               "(syn17024173) - use get_valid_programs() rather than hardcoding.",
    "Study": "SynID of the study's TOP-LEVEL folder (not the study name).",
    "Study_Abbreviation": "Short-form study name. Must exactly match the 'study' annotation "
                          "used on the study's data/metadata files.",
    "DataType_All": "Title Case with spaces, matching the 'dataType' attribute in the data model "
                    "(e.g. 'Gene Expression'). Exceptions: 'Harmonized Metadata', "
                    "'Harmonized Experimental Data', 'Analysis'.",
    "Study_Name": "Long-form name followed by the short name in parentheses, "
                  "e.g. 'The Example Study (EXAMPLE)'.",
    "Study_Description": "ONE sentence, starting with 'This study provides...'. Max 440 characters.",
    "specimenType": "Title Case with spaces. Match existing values where possible; see "
                    "SPECIMEN_TYPE_VALUES for the SOP's known list.",
    "studyFocus": "Maps to 'diagnosis' in the data model. Only the primary scientific focus - "
                  "do not list control populations. Avoid apostrophes ('Alzheimer Disease', not "
                  "'Alzheimer's Disease').",
    "Data_Contributor": "Institution name, ROR standard where possible (https://ror.org/) - "
                        "check spelling/capitalization against existing table values.",
    "Species": "Use the value as it appears in the data model; see SPECIES_VALUES.",
    "isModelSystem": "True if the study involves model system components (iPSC, organoids, etc.) "
                     "- all animal studies are also model systems. False for most human studies.",
    "Grant Number": "One grant number per list item. For NIH grants, omit the application type, "
                    "support year, and extension suffix - activity code through serial number only "
                    "(e.g. 'R01AG046171', not '1R01AG046171-01A1'). Industry/nonprofit grants: enter as provided.",
    "Methods": "SynID(s) of the folder(s) whose wiki holds the Methods description for that assay "
              "type, comma-separated for multiple.",
    "Related_Studies": "SynID(s) of related studies, comma-separated. Don't add without direction "
                       "from contributors/PIs.",
    "isFeatured": "Defaults to false. Set to true only when requested by the business owner.",
    "Acknowledgement": "Format '<wiki project synID>/wiki/<subpage id>', e.g. 'syn12666371/wiki/602387'. "
                       "Requires first creating the acknowledgement wiki subpage under syn12666371/wiki/602387.",
    "ackContext": "One of ACK_CONTEXT_STANDARD / ACK_CONTEXT_REPROCESSED / ACK_CONTEXT_UCI_CLU_H2KBKI "
                 "(most studies use ACK_CONTEXT_STANDARD).",
    "studyMetadata": "One of the STUDY_METADATA_* constants; most studies use STUDY_METADATA_STANDARD "
                     "(ADNI/ROSMAP/MayoRNAseq/MSBB have their own).",
    "accessReqs": "One of the ACCESS_REQS_* constants, based on controlled (human)/open (model, animal)/ADNI access.",
    "Citations": DEPRECATED_COLUMNS["Citations"],
    "DOI": "Minted DOI URL, added after the acknowledgement statement is set up.",
    "groupByGrantNumber": "Defaults to true. Set to false to keep studies/projects from surfacing together on the portal.",
}

# hard, Synapse-enforced enum (unlike the *_VALUES sets below, which are free
# text with a UI facet filter, not a real constraint)
ENUM_VALUES = {"Study_Type": ["Consortium", "Individual"]}

# SOP's known specimenType values (extensible - draw new terms from the data model's
# organ/tissue or model-system vocab if a new type is genuinely needed).
SPECIMEN_TYPE_VALUES = {
    "Blood", "Brain", "Cecum", "Cell Line", "Cerebrospinal Fluid", "Fecal Material",
    "Fibroblasts", "iPSC", "Liver", "Neurons", "Organoid", "Plasma", "Primary Cells",
    "Serum", "Not Assigned",
}

# SOP's official Species list. Note: the live table also contains a few legacy/special
# values (e.g. "Drosophila melanogaster", "Marmoset") predating this convention.
SPECIES_VALUES = {"Drosophila", "Human", "Mouse", "Rat"}

ACK_CONTEXT_STANDARD = "syn12666371/wiki/617506"
ACK_CONTEXT_REPROCESSED = "syn12666371/wiki/617507"
ACK_CONTEXT_UCI_CLU_H2KBKI = "syn12666371/wiki/633566"  # temporary, study-specific
ACK_CONTEXT_VALUES = {ACK_CONTEXT_STANDARD, ACK_CONTEXT_REPROCESSED, ACK_CONTEXT_UCI_CLU_H2KBKI}

STUDY_METADATA_STANDARD = "syn12666371/wiki/607136"
STUDY_METADATA_ADNI = "syn12666371/wiki/608609"
STUDY_METADATA_ROSMAP = "syn12666371/wiki/638912"
STUDY_METADATA_MAYORNASEQ = "syn23634010"  # includes special considerations
STUDY_METADATA_MSBB = "syn7392158"  # includes special considerations
STUDY_METADATA_VALUES = {
    STUDY_METADATA_STANDARD, STUDY_METADATA_ADNI, STUDY_METADATA_ROSMAP,
    STUDY_METADATA_MAYORNASEQ, STUDY_METADATA_MSBB,
}

ACCESS_REQS_CONTROLLED = "syn12666371/wiki/595380"
ACCESS_REQS_OPEN = "syn12666371/wiki/608104"
ACCESS_REQS_ADNI = "syn12666371/wiki/608105"
ACCESS_REQS_FRAMINGHAM = "syn12666371/wiki/608314"  # available but unused per SOP
ACCESS_REQS_VALUES = {ACCESS_REQS_CONTROLLED, ACCESS_REQS_OPEN, ACCESS_REQS_ADNI, ACCESS_REQS_FRAMINGHAM}

# Business rule from the SOP is stricter than the column's technical max (700):
# a one-sentence description starting with "This study provides...".
STUDY_DESCRIPTION_MAX_SIZE = 440

# ==============================================================================
# EDIT THIS SECTION, then run this file. Leave a field as None if you don't
# have that information yet (see the SOP - partial rows are fine, they'll just
# show an incomplete public study page until filled in). For what each field
# means and its valid values, see the SOP REFERENCE section above, or run
# `python -c "from adkp_studies_table import print_column_guide; print_column_guide()"`.
#
# Set MODE to "add" for a brand-new study, or "update" to revise fields on a
# study already in the table (e.g. a fuller Study_Description once more info
# comes in from the contributor) - that rewrites the existing row in place
# instead of creating a duplicate.
# ==============================================================================

DRY_RUN = True  # True: only print the validation report, submit nothing.
                # False: submit/update the live table if there are no errors.

MODE = "add"  # "add" (uses STUDY_ROW below) or "update" (uses STUDY_UPDATES below)

STUDY_ROW = {
    "Study_Type": "Individual",                # "Individual" or "Consortium"
    "Program": ["AMP-AD"],                      # must match the ADKP Programs table (syn17024173)
    "Study": "syn00000000",                     # synID of the study's TOP-LEVEL folder
    "Study_Abbreviation": "EXAMPLE",
    "DataType_All": ["Gene Expression"],
    "Study_Name": "The Example Study (EXAMPLE)",
    "Study_Description": "This study provides gene expression data from brain tissue in Alzheimer Disease.",
    "specimenType": ["Brain"],
    "studyFocus": ["Alzheimer Disease"],
    "Data_Contributor": ["Example University"],
    "Species": ["Human"],
    "isModelSystem": False,
    "Grant Number": ["U01AG000000"],
    "Methods": None,                            # synID(s) of folder(s) with a Methods wiki, comma-separated
    "Related_Studies": None,                    # synID(s) of related studies, comma-separated
    "isFeatured": False,
    "Acknowledgement": "syn12666371/wiki/000000",  # create the wiki subpage first - see COLUMN_NOTES above
    "ackContext": ACK_CONTEXT_STANDARD,            # see ACK_CONTEXT_* above for alternatives
    "studyMetadata": STUDY_METADATA_STANDARD,      # see STUDY_METADATA_* above for alternatives
    "accessReqs": ACCESS_REQS_CONTROLLED,          # see ACCESS_REQS_* above for alternatives
    "DOI": None,
    "groupByGrantNumber": True,
}

# Only used when MODE == "update": which existing row to revise, identified by
# its Study_Abbreviation (must match exactly one row), and only the field(s)
# you want to change - any key also valid in STUDY_ROW is fine here, in the
# same format (e.g. lists for STRING_LIST columns).
UPDATE_STUDY_ABBREVIATION = "EXAMPLE"

STUDY_UPDATES = {
    "Study_Description": "This study provides updated gene expression data with additional detail.",
}

# ==============================================================================
# Library code below - shouldn't need to edit past this point.
# ==============================================================================

STUDIES_TABLE_ID = "syn17083367"
PROGRAMS_TABLE_ID = "syn17024173"  # ADKP Programs table - authoritative list of valid Program values

ALL_COLUMNS = [
    "Study_Type", "Program", "Study", "Study_Abbreviation", "DataType_All",
    "Study_Name", "Study_Description", "specimenType", "studyFocus",
    "Data_Contributor", "Species", "isModelSystem", "Grant Number", "Methods",
    "Related_Studies", "isFeatured", "Acknowledgement", "ackContext",
    "studyMetadata", "accessReqs", "Citations", "DOI", "groupByGrantNumber",
]

# name -> max character length (STRING columns only, per the Synapse column schema)
STRING_MAX_SIZE = {
    "Study_Type": 10,
    "Study_Abbreviation": 50,
    "Study_Name": 250,
    "Study_Description": 700,
    "Methods": 400,
    "Related_Studies": 400,
    "Acknowledgement": 50,
    "ackContext": 50,
    "studyMetadata": 50,
    "accessReqs": 50,
    "Citations": 50,
    "DOI": 50,
}

# Matches the "core" of an NIH activity-code grant number (e.g. R01AG046171, RF1AG051504,
# U19AG063744) so the leading-digit/suffix check below doesn't fire on free-text values
# like "cross-consortium" or "GSK" that also happen to contain a hyphen.
_NIH_GRANT_CORE_RE = re.compile(r"[A-Z]{1,3}\d{2}[A-Z]{0,2}\d{5,7}")

# name -> max number of items (STRING_LIST columns)
LIST_COLUMNS = {
    "Program": 10,
    "DataType_All": 10,
    "specimenType": 20,
    "studyFocus": 10,
    "Data_Contributor": 10,
    "Species": 10,
    "Grant Number": 10,
}

BOOLEAN_COLUMNS = ["isModelSystem", "isFeatured", "groupByGrantNumber"]

# must be a valid Synapse entity ID (e.g. "syn12345") identifying the study's project/folder
ENTITY_COLUMNS = ["Study"]


def login(auth_token=None):
    """Log in to Synapse. Falls back to ~/.synapseConfig / SYNAPSE_AUTH_TOKEN if auth_token is None."""
    syn = synapseclient.Synapse()
    syn.login(authToken=auth_token)
    return syn


def get_table_schema(syn):
    """Fetch the live column schema from Synapse, keyed by column name."""
    return {c.name: c for c in syn.getTableColumns(STUDIES_TABLE_ID)}


def new_study_row():
    """Blank template dict with every column present, set to None. Fill in what you need."""
    return {col: None for col in ALL_COLUMNS}


def get_known_values(syn, columns=tuple(LIST_COLUMNS)):
    """
    Query the table for distinct values already in use for each STRING_LIST column.
    Useful for validating spelling/consistency before adding a new row, since these
    columns are free text, not hard-constrained enums.
    """
    known = {}
    for col in columns:
        col_sql = f'"{col}"' if " " in col else col
        df = syn.tableQuery(f"SELECT DISTINCT {col_sql} FROM {STUDIES_TABLE_ID}").asDataFrame()
        values = set()
        for cell in df[col].dropna():
            values.update(cell if isinstance(cell, list) else [cell])
        known[col] = values
    return known


def get_valid_programs(syn):
    """
    Fetch the authoritative list of Program values from the ADKP Programs table
    (syn17024173), per the SOP's instruction to match that table rather than
    whatever happens to already be in use in the Studies table.
    """
    df = syn.tableQuery(f"SELECT Program FROM {PROGRAMS_TABLE_ID}").asDataFrame()
    return set(df["Program"].dropna())


def print_column_guide(columns=ALL_COLUMNS):
    """Print the SOP's per-column guidance - handy when filling in a row by hand."""
    for col in columns:
        print(f"{col}:\n    {COLUMN_NOTES.get(col, '(no note)')}\n")


def _check_str(name, value, issues):
    max_size = STRING_MAX_SIZE.get(name)
    if max_size and value is not None and len(str(value)) > max_size:
        issues.append({"column": name, "level": "ERROR", "value": value,
                        "message": f"exceeds max length {max_size}"})


def _check_list(name, value, issues):
    if value is None:
        return
    if not isinstance(value, list):
        issues.append({"column": name, "level": "ERROR", "value": value,
                        "message": f"must be a list, got {type(value).__name__}"})
        return
    max_len = LIST_COLUMNS[name]
    if len(value) > max_len:
        issues.append({"column": name, "level": "ERROR", "value": value,
                        "message": f"has {len(value)} items, max is {max_len}"})
    for item in value:
        if len(str(item)) > 50:
            issues.append({"column": name, "level": "ERROR", "value": item,
                            "message": "item exceeds typical max item length (50 chars)"})


def _collect_issues(row, known_values=None, valid_programs=None):
    """Run every check against a row dict and return a list of issue dicts (column/level/value/message)."""
    issues = []

    unknown_cols = set(row) - set(ALL_COLUMNS)
    for name in unknown_cols:
        issues.append({"column": name, "level": "ERROR", "value": row[name], "message": "not a table column"})

    for name, guidance in DEPRECATED_COLUMNS.items():
        if row.get(name):
            issues.append({"column": name, "level": "ERROR", "value": row.get(name),
                            "message": f"deprecated - {guidance}"})

    for name in STRING_MAX_SIZE:
        _check_str(name, row.get(name), issues)

    description = row.get("Study_Description")
    if description is not None and len(description) > STUDY_DESCRIPTION_MAX_SIZE:
        issues.append({"column": "Study_Description", "level": "ERROR", "value": description,
                        "message": f"exceeds SOP max of {STUDY_DESCRIPTION_MAX_SIZE} characters "
                                   f"({len(description)} chars)"})
    if description is not None and not description.startswith("This study provides"):
        issues.append({"column": "Study_Description", "level": "WARNING", "value": description,
                        "message": "should start with 'This study provides...' per SOP"})

    for name in LIST_COLUMNS:
        _check_list(name, row.get(name), issues)

    study_type = row.get("Study_Type")
    if study_type is not None and study_type not in ENUM_VALUES["Study_Type"]:
        issues.append({"column": "Study_Type", "level": "ERROR", "value": study_type,
                        "message": f"must be one of {ENUM_VALUES['Study_Type']}"})

    for name in BOOLEAN_COLUMNS:
        if row.get(name) is not None and not isinstance(row[name], bool):
            issues.append({"column": name, "level": "ERROR", "value": row[name],
                            "message": f"must be a bool, got {type(row[name]).__name__}"})

    for name in ENTITY_COLUMNS:
        value = row.get(name)
        if value is not None and not str(value).startswith("syn"):
            issues.append({"column": name, "level": "ERROR", "value": value,
                            "message": "must be a Synapse entity ID (e.g. 'syn12345')"})

    if valid_programs is not None:
        for p in row.get("Program") or []:
            if p not in valid_programs:
                issues.append({"column": "Program", "level": "ERROR", "value": p,
                                "message": f"not in the ADKP Programs table ({PROGRAMS_TABLE_ID}) - "
                                           f"check spelling or add it there first"})

    for v in row.get("specimenType") or []:
        if v not in SPECIMEN_TYPE_VALUES:
            issues.append({"column": "specimenType", "level": "WARNING", "value": v,
                            "message": "not in the SOP's known list - if genuinely new, draw the term "
                                       "from the data model's organ/tissue vocab"})

    for v in row.get("Species") or []:
        if v not in SPECIES_VALUES:
            issues.append({"column": "Species", "level": "WARNING", "value": v,
                            "message": f"not in the SOP's official list ({sorted(SPECIES_VALUES)})"})

    for v in row.get("Grant Number") or []:
        if _NIH_GRANT_CORE_RE.search(v) and (v[0].isdigit() or "-" in v):
            issues.append({"column": "Grant Number", "level": "WARNING", "value": v,
                            "message": "looks like it still has an application type prefix or extension "
                                       "suffix - trim to activity code through serial number (e.g. 'R01AG046171')"})

    for name, allowed in (("ackContext", ACK_CONTEXT_VALUES),
                          ("studyMetadata", STUDY_METADATA_VALUES),
                          ("accessReqs", ACCESS_REQS_VALUES)):
        value = row.get(name)
        if value is not None and value not in allowed:
            issues.append({"column": name, "level": "WARNING", "value": value,
                            "message": f"doesn't match one of the SOP's known reference IDs "
                                       f"({sorted(allowed)}) - confirm this is intentional"})

    acknowledgement = row.get("Acknowledgement")
    if acknowledgement is not None and not re.match(r"^syn\d+/wiki/\d+$", acknowledgement):
        issues.append({"column": "Acknowledgement", "level": "WARNING", "value": acknowledgement,
                        "message": "doesn't match the expected '<synID>/wiki/<subpage id>' format"})

    if known_values:
        for name, existing in known_values.items():
            for v in row.get(name) or []:
                if v not in existing:
                    issues.append({"column": name, "level": "WARNING", "value": v,
                                    "message": "not among existing values in the table - "
                                               "double check spelling/consistency"})

    return issues


def validate_row(row, known_values=None, valid_programs=None):
    """
    Validate a study row dict against the table's column constraints and the SOP's
    business rules. Raises on the first ERROR-level issue; prints any WARNING-level
    issues. For a full table of every issue at once (nothing raised), use
    validate_row_report() instead.
    """
    issues = _collect_issues(row, known_values=known_values, valid_programs=valid_programs)
    for issue in issues:
        if issue["level"] == "ERROR":
            raise ValueError(f"{issue['column']}: {issue['message']} (value: {issue['value']!r})")
    for issue in issues:
        print(f"Warning: {issue['column']} = {issue['value']!r} - {issue['message']}")
    return True


def validate_row_report(row, known_values=None, valid_programs=None):
    """
    Same checks as validate_row(), but returns every issue as a pandas DataFrame
    (columns: column, level, value, message) instead of raising or printing.
    Empty DataFrame means the row is clean. Handy for reviewing everything at
    once, e.g. `report = validate_row_report(row); report` in a notebook.
    """
    issues = _collect_issues(row, known_values=known_values, valid_programs=valid_programs)
    return pd.DataFrame(issues, columns=["column", "level", "value", "message"])


def validate_rows_report(rows, known_values=None, valid_programs=None):
    """Same as validate_row_report(), but for a list of row dicts - adds a 'row_index' column."""
    frames = []
    for i, row in enumerate(rows):
        df = validate_row_report(row, known_values=known_values, valid_programs=valid_programs)
        df.insert(0, "row_index", i)
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["row_index", "column", "level", "value", "message"])


def add_study_row(syn, row, known_values=None, valid_programs=None):
    """Validate and append a single new row (dict) to the ADKP Portal Studies table."""
    validate_row(row, known_values=known_values, valid_programs=valid_programs)
    ordered = {col: row.get(col) for col in ALL_COLUMNS}
    df = pd.DataFrame([ordered])
    syn.store(Table(STUDIES_TABLE_ID, df))


def add_study_rows(syn, rows, known_values=None, valid_programs=None):
    """Validate and append multiple new rows (list of dicts) in one call."""
    for row in rows:
        validate_row(row, known_values=known_values, valid_programs=valid_programs)
    ordered = [{col: row.get(col) for col in ALL_COLUMNS} for row in rows]
    df = pd.DataFrame(ordered)
    syn.store(Table(STUDIES_TABLE_ID, df))


def update_study_row(syn, row_id, updates):
    """Update specific columns of an existing row, identified by its Synapse ROW_ID."""
    df = syn.tableQuery(f"SELECT * FROM {STUDIES_TABLE_ID} WHERE ROW_ID = {row_id}").asDataFrame()
    if df.empty:
        raise ValueError(f"No row found with ROW_ID={row_id}")
    for col, val in updates.items():
        df.at[df.index[0], col] = val
    syn.store(Table(STUDIES_TABLE_ID, df))


def find_study_row_id(syn, study_abbreviation):
    """
    Look up the ROW_ID of the existing row for a study, by its Study_Abbreviation,
    for use with update_study_row(). Raises if zero or more than one row matches.
    """
    df = syn.tableQuery(
        f"SELECT ROW_ID FROM {STUDIES_TABLE_ID} WHERE Study_Abbreviation = '{study_abbreviation}'"
    ).asDataFrame()
    if df.empty:
        raise ValueError(f"No row found with Study_Abbreviation={study_abbreviation!r}")
    if len(df) > 1:
        raise ValueError(f"Multiple rows found with Study_Abbreviation={study_abbreviation!r} "
                          f"(ROW_IDs: {list(df['ROW_ID'])}) - use update_study_row() directly "
                          f"with the correct ROW_ID")
    return int(df["ROW_ID"].iloc[0])


if __name__ == "__main__":
    if MODE not in ("add", "update"):
        raise ValueError(f"MODE must be 'add' or 'update', got {MODE!r}")

    syn = login()
    known = get_known_values(syn)
    programs = get_valid_programs(syn)

    if MODE == "add":
        report = validate_row_report(STUDY_ROW, known_values=known, valid_programs=programs)
        if report.empty:
            print("No issues found.")
        else:
            print(report.to_string(index=False))

        has_errors = not report.empty and (report["level"] == "ERROR").any()

        if DRY_RUN:
            print("\nDRY_RUN is True - nothing was submitted. Set DRY_RUN = False at the top of "
                  "this file to submit STUDY_ROW as a new row once the report above looks right.")
        elif has_errors:
            print("\nNot submitting: fix the ERROR-level issue(s) above first.")
        else:
            add_study_row(syn, STUDY_ROW, known_values=known, valid_programs=programs)
            print("\nRow submitted to the ADKP Portal Studies Table.")
    else:
        row_id = find_study_row_id(syn, UPDATE_STUDY_ABBREVIATION)
        print(f"Found ROW_ID {row_id} for Study_Abbreviation={UPDATE_STUDY_ABBREVIATION!r}.")

        report = validate_row_report(STUDY_UPDATES, known_values=known, valid_programs=programs)
        if report.empty:
            print("No issues found.")
        else:
            print(report.to_string(index=False))

        has_errors = not report.empty and (report["level"] == "ERROR").any()

        if DRY_RUN:
            print(f"\nDRY_RUN is True - nothing was updated. Set DRY_RUN = False at the top of "
                  f"this file to apply STUDY_UPDATES to ROW_ID {row_id} once the report above looks right.")
        elif has_errors:
            print("\nNot updating: fix the ERROR-level issue(s) above first.")
        else:
            update_study_row(syn, row_id, STUDY_UPDATES)
            print(f"\nROW_ID {row_id} updated in the ADKP Portal Studies Table.")
