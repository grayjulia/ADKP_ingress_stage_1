# Reusable helpers for adding and updating rows in the ADKP Portal Studies table
# (syn17083367 - https://www.synapse.org/Synapse:syn17083367/tables/).
#
# Schema constants (column names/types/sizes) were pulled live from Synapse's
# table schema on 2026-08-26 via GET /entity/syn17083367/column. Business rules
# (controlled vocabularies, formatting conventions, deprecated columns) come from
# the SOP "Add or Update Portal Study Tables (ELITE and ADKP Portals)" v2.1
# (Confluence AD space, page 4566515713), section 5.1.2, fetched 2026-08-26.
# Re-check that page if this table's conventions seem to have changed - it is
# the source of truth for *why* a value is entered a certain way, while the
# Synapse column API is the source of truth for what the table will *accept*.
#
# Setup:
#   install.packages("synapser", repos = "https://sage-bionetworks.github.io/ran")
#   Authenticate once via synLogin() with a personal access token, or set
#   SYNAPSE_AUTH_TOKEN in your environment - do not hardcode credentials here.
#
# To use: edit STUDY_ROW and DRY_RUN below, then run this file
# (Rscript adkp_studies_table.R, or source() it in RStudio). It always prints
# a validation table; it only submits to Synapse if DRY_RUN is FALSE and there
# are no ERROR-level issues.
#
# STRING_LIST columns (Program, DataType_All, specimenType, studyFocus,
# Data_Contributor, Species, "Grant Number"): confirmed against real data on
# 2026-08-26, and matching synapser's own vignette (inst/doc/views.R), the
# CSV-based Table()/synStore() write path expects each cell to be a plain
# character value holding a JSON-encoded array (e.g. '["AMP-AD"]'), produced
# via rjson::toJSON(as.list(...)) - NOT an R list-column. Reading a table back
# also returns these as the same raw JSON-string text (not parsed R lists);
# get_known_values() unpacks them with rjson::fromJSON() for comparison.

library(synapser)

# ==============================================================================
# SOP REFERENCE - read this before filling in STUDY_ROW below. Condensed from
# section 5.1.2 of the SOP "Add or Update Portal Study Tables (ELITE and ADKP
# Portals)" v2.1 (Confluence AD space, page 4566515713), fetched 2026-08-26.
# ==============================================================================

# Columns the SOP says are deprecated - do not populate.
DEPRECATED_COLUMNS <- list(
  Citations = paste(
    "Deprecated - leave blank. A publications scraper (GitHub Action)",
    "maintains citation data separately; do not manually enter it."
  )
)

# Per-column guidance condensed from SOP section 5.1.2, keyed by column name.
COLUMN_NOTES <- list(
  Study_Type = paste(
    "Almost all studies are 'Individual'. 'Consortium' is reserved for",
    "cross-consortium efforts (e.g. reprocessing studies) - verify with the business owner."
  ),
  Program = paste(
    "Multiple allowed. Must match the current values in the ADKP Programs table",
    "(syn17024173) - use get_valid_programs() rather than hardcoding."
  ),
  Study = "SynID of the study's TOP-LEVEL folder (not the study name).",
  Study_Abbreviation = paste(
    "Short-form study name. Must exactly match the 'study' annotation",
    "used on the study's data/metadata files."
  ),
  DataType_All = paste(
    "Title Case with spaces, matching the 'dataType' attribute in the data model",
    "(e.g. 'Gene Expression'). Exceptions: 'Harmonized Metadata',",
    "'Harmonized Experimental Data', 'Analysis'."
  ),
  Study_Name = paste(
    "Long-form name followed by the short name in parentheses,",
    "e.g. 'The Example Study (EXAMPLE)'."
  ),
  Study_Description = "ONE sentence, starting with 'This study provides...'. Max 440 characters.",
  specimenType = paste(
    "Title Case with spaces. Match existing values where possible; see",
    "SPECIMEN_TYPE_VALUES for the SOP's known list."
  ),
  studyFocus = paste(
    "Maps to 'diagnosis' in the data model. Only the primary scientific focus -",
    "do not list control populations. Avoid apostrophes ('Alzheimer Disease', not",
    "'Alzheimer's Disease')."
  ),
  Data_Contributor = paste(
    "Institution name, ROR standard where possible (https://ror.org/) -",
    "check spelling/capitalization against existing table values."
  ),
  Species = "Use the value as it appears in the data model; see SPECIES_VALUES.",
  isModelSystem = paste(
    "True if the study involves model system components (iPSC, organoids, etc.)",
    "- all animal studies are also model systems. False for most human studies."
  ),
  `Grant Number` = paste(
    "One grant number per list item. For NIH grants, omit the application type,",
    "support year, and extension suffix - activity code through serial number only",
    "(e.g. 'R01AG046171', not '1R01AG046171-01A1'). Industry/nonprofit grants: enter as provided."
  ),
  Methods = paste(
    "SynID(s) of the folder(s) whose wiki holds the Methods description for that assay",
    "type, comma-separated for multiple."
  ),
  Related_Studies = paste(
    "SynID(s) of related studies, comma-separated. Don't add without direction",
    "from contributors/PIs."
  ),
  isFeatured = "Defaults to false. Set to true only when requested by the business owner.",
  Acknowledgement = paste(
    "Format '<wiki project synID>/wiki/<subpage id>', e.g. 'syn12666371/wiki/602387'.",
    "Requires first creating the acknowledgement wiki subpage under syn12666371/wiki/602387."
  ),
  ackContext = paste(
    "One of ACK_CONTEXT_STANDARD / ACK_CONTEXT_REPROCESSED / ACK_CONTEXT_UCI_CLU_H2KBKI",
    "(most studies use ACK_CONTEXT_STANDARD)."
  ),
  studyMetadata = paste(
    "One of the STUDY_METADATA_* constants; most studies use STUDY_METADATA_STANDARD",
    "(ADNI/ROSMAP/MayoRNAseq/MSBB have their own)."
  ),
  accessReqs = "One of the ACCESS_REQS_* constants, based on controlled (human)/open (model, animal)/ADNI access.",
  Citations = DEPRECATED_COLUMNS$Citations,
  DOI = "Minted DOI URL, added after the acknowledgement statement is set up.",
  groupByGrantNumber = "Defaults to true. Set to false to keep studies/projects from surfacing together on the portal."
)

# hard, Synapse-enforced enum (unlike the *_VALUES lists below, which are free
# text with a UI facet filter, not a real constraint)
ENUM_VALUES <- list(Study_Type = c("Consortium", "Individual"))

# SOP's known specimenType values (extensible - draw new terms from the data model's
# organ/tissue or model-system vocab if a new type is genuinely needed).
SPECIMEN_TYPE_VALUES <- c(
  "Blood", "Brain", "Cecum", "Cell Line", "Cerebrospinal Fluid", "Fecal Material",
  "Fibroblasts", "iPSC", "Liver", "Neurons", "Organoid", "Plasma", "Primary Cells",
  "Serum", "Not Assigned"
)

# SOP's official Species list. Note: the live table also contains a few legacy/special
# values (e.g. "Drosophila melanogaster", "Marmoset") predating this convention.
SPECIES_VALUES <- c("Drosophila", "Human", "Mouse", "Rat")

ACK_CONTEXT_STANDARD <- "syn12666371/wiki/617506"
ACK_CONTEXT_REPROCESSED <- "syn12666371/wiki/617507"
ACK_CONTEXT_UCI_CLU_H2KBKI <- "syn12666371/wiki/633566"  # temporary, study-specific
ACK_CONTEXT_VALUES <- c(ACK_CONTEXT_STANDARD, ACK_CONTEXT_REPROCESSED, ACK_CONTEXT_UCI_CLU_H2KBKI)

STUDY_METADATA_STANDARD <- "syn12666371/wiki/607136"
STUDY_METADATA_ADNI <- "syn12666371/wiki/608609"
STUDY_METADATA_ROSMAP <- "syn12666371/wiki/638912"
STUDY_METADATA_MAYORNASEQ <- "syn23634010"  # includes special considerations
STUDY_METADATA_MSBB <- "syn7392158"  # includes special considerations
STUDY_METADATA_VALUES <- c(
  STUDY_METADATA_STANDARD, STUDY_METADATA_ADNI, STUDY_METADATA_ROSMAP,
  STUDY_METADATA_MAYORNASEQ, STUDY_METADATA_MSBB
)

ACCESS_REQS_CONTROLLED <- "syn12666371/wiki/595380"
ACCESS_REQS_OPEN <- "syn12666371/wiki/608104"
ACCESS_REQS_ADNI <- "syn12666371/wiki/608105"
ACCESS_REQS_FRAMINGHAM <- "syn12666371/wiki/608314"  # available but unused per SOP
ACCESS_REQS_VALUES <- c(ACCESS_REQS_CONTROLLED, ACCESS_REQS_OPEN, ACCESS_REQS_ADNI, ACCESS_REQS_FRAMINGHAM)

# Business rule from the SOP is stricter than the column's technical max (700):
# a one-sentence description starting with "This study provides...".
STUDY_DESCRIPTION_MAX_SIZE <- 440

# ==============================================================================
# EDIT THIS SECTION, then run this file. Leave a field as NA if you don't have
# that information yet (see the SOP - partial rows are fine, they'll just show
# an incomplete public study page until filled in). For what each field means
# and its valid values, see the SOP REFERENCE section above, or run
# print_column_guide() after sourcing this file.
#
# Set MODE to "add" for a brand-new study, or "update" to revise fields on a
# study already in the table (e.g. a fuller Study_Description once more info
# comes in from the contributor) - that rewrites the existing row in place
# instead of creating a duplicate.
# ==============================================================================

DRY_RUN <- TRUE  # TRUE: only print the validation report, submit nothing.
                 # FALSE: submit/update the live table if there are no errors.

MODE <- "add"  # "add" (uses STUDY_ROW below) or "update" (uses STUDY_UPDATES below)

STUDY_ROW <- list(
  Study_Type = "Individual",                   # "Individual" or "Consortium"
  Program = list("AMP-AD"),                    # must match the ADKP Programs table (syn17024173)
  Study = "syn00000000",                       # synID of the study's TOP-LEVEL folder
  Study_Abbreviation = "EXAMPLE",
  DataType_All = list("Gene Expression"),
  Study_Name = "The Example Study (EXAMPLE)",
  Study_Description = "This study provides gene expression data from brain tissue in Alzheimer Disease.",
  specimenType = list("Brain"),
  studyFocus = list("Alzheimer Disease"),
  Data_Contributor = list("Example University"),
  Species = list("Human"),
  isModelSystem = FALSE,
  `Grant Number` = list("U01AG000000"),
  Methods = NA,                                # synID(s) of folder(s) with a Methods wiki, comma-separated
  Related_Studies = NA,                        # synID(s) of related studies, comma-separated
  isFeatured = FALSE,
  Acknowledgement = "syn12666371/wiki/000000",  # create the wiki subpage first - see COLUMN_NOTES above
  ackContext = ACK_CONTEXT_STANDARD,            # see ACK_CONTEXT_* above for alternatives
  studyMetadata = STUDY_METADATA_STANDARD,      # see STUDY_METADATA_* above for alternatives
  accessReqs = ACCESS_REQS_CONTROLLED,          # see ACCESS_REQS_* above for alternatives
  DOI = NA,
  groupByGrantNumber = TRUE
)

# Only used when MODE == "update": which existing row to revise, identified by
# its Study_Abbreviation (must match exactly one row), and only the field(s)
# you want to change - any column also valid in STUDY_ROW is fine here, in the
# same format (e.g. lists for STRING_LIST columns).
UPDATE_STUDY_ABBREVIATION <- "EXAMPLE"

STUDY_UPDATES <- list(
  Study_Description = "This study provides updated gene expression data with additional detail."
)

# ==============================================================================
# Library code below - shouldn't need to edit past this point.
# ==============================================================================

STUDIES_TABLE_ID <- "syn17083367"
PROGRAMS_TABLE_ID <- "syn17024173"  # ADKP Programs table - authoritative list of valid Program values

ALL_COLUMNS <- c(
  "Study_Type", "Program", "Study", "Study_Abbreviation", "DataType_All",
  "Study_Name", "Study_Description", "specimenType", "studyFocus",
  "Data_Contributor", "Species", "isModelSystem", "Grant Number", "Methods",
  "Related_Studies", "isFeatured", "Acknowledgement", "ackContext",
  "studyMetadata", "accessReqs", "Citations", "DOI", "groupByGrantNumber"
)

# name -> max character length (STRING columns only, per the Synapse column schema)
STRING_MAX_SIZE <- list(
  Study_Type = 10,
  Study_Abbreviation = 50,
  Study_Name = 250,
  Study_Description = 700,
  Methods = 400,
  Related_Studies = 400,
  Acknowledgement = 50,
  ackContext = 50,
  studyMetadata = 50,
  accessReqs = 50,
  Citations = 50,
  DOI = 50
)

# Matches the "core" of an NIH activity-code grant number (e.g. R01AG046171, RF1AG051504,
# U19AG063744) so the leading-digit/suffix check below doesn't fire on free-text values
# like "cross-consortium" or "GSK" that also happen to contain a hyphen.
.NIH_GRANT_CORE_RE <- "[A-Z]{1,3}[0-9]{2}[A-Z]{0,2}[0-9]{5,7}"

# name -> max number of items (STRING_LIST columns)
LIST_COLUMNS <- list(
  Program = 10,
  DataType_All = 10,
  specimenType = 20,
  studyFocus = 10,
  Data_Contributor = 10,
  Species = 10,
  `Grant Number` = 10
)

BOOLEAN_COLUMNS <- c("isModelSystem", "isFeatured", "groupByGrantNumber")

# must be a valid Synapse entity ID (e.g. "syn12345") identifying the study's project/folder
ENTITY_COLUMNS <- c("Study")

login_synapse <- function(auth_token = NULL) {
  if (!is.null(auth_token)) {
    synLogin(authToken = auth_token)
  } else {
    synLogin()  # uses cached credentials / SYNAPSE_AUTH_TOKEN env var
  }
}

get_table_schema <- function() {
  # Returns the live column definitions from Synapse for this table.
  synRestGET(sprintf("/entity/%s/column", STUDIES_TABLE_ID))$results
}

new_study_row <- function() {
  row <- as.list(rep(NA, length(ALL_COLUMNS)))
  names(row) <- ALL_COLUMNS
  row
}

# synapser's as.data.frame() returns STRING_LIST cells as literal JSON array
# strings (e.g. '["AMP-AD", "M2OVE-AD"]'), not parsed R lists - confirmed against
# the live table on 2026-08-26. rjson (already a synapser dependency) unpacks them.
.parse_json_list_cell <- function(x) {
  if (is.na(x) || identical(x, "")) return(character(0))
  tryCatch(unlist(rjson::fromJSON(x)), error = function(e) x)
}

get_known_values <- function(columns = names(LIST_COLUMNS)) {
  # Distinct values already in use for each STRING_LIST column, for
  # validating spelling/consistency before adding a new row.
  known <- list()
  for (col in columns) {
    col_sql <- if (grepl(" ", col)) sprintf('"%s"', col) else col
    query <- synTableQuery(sprintf("SELECT DISTINCT %s FROM %s", col_sql, STUDIES_TABLE_ID))
    df <- as.data.frame(query)
    values <- unique(unlist(lapply(df[[col]], .parse_json_list_cell)))
    known[[col]] <- values[!is.na(values)]
  }
  known
}

get_valid_programs <- function() {
  # Authoritative list of Program values from the ADKP Programs table (syn17024173),
  # per the SOP's instruction to match that table rather than whatever happens to
  # already be in use in the Studies table.
  query <- synTableQuery(sprintf("SELECT Program FROM %s", PROGRAMS_TABLE_ID))
  df <- as.data.frame(query)
  unique(df$Program[!is.na(df$Program)])
}

print_column_guide <- function(columns = ALL_COLUMNS) {
  # The SOP's per-column guidance - handy when filling in a row by hand.
  for (col in columns) {
    note <- COLUMN_NOTES[[col]]
    if (is.null(note)) note <- "(no note)"
    cat(sprintf("%s:\n    %s\n\n", col, note))
  }
}

.new_issue <- function(column, level, value, message) {
  data.frame(column = column, level = level, value = paste(value, collapse = ", "),
             message = message, stringsAsFactors = FALSE)
}

.collect_issues <- function(row, known_values = NULL, valid_programs = NULL) {
  # known_values: optional list from get_known_values() - mismatches here are
  # warnings, not errors, since most list columns aren't hard-enforced enums.
  # valid_programs: optional character vector from get_valid_programs() - values
  # in Program not in this set are ERRORs, since the SOP treats the Programs
  # table as the authoritative list.
  issues <- list()
  add <- function(column, level, value, message) {
    issues[[length(issues) + 1]] <<- .new_issue(column, level, value, message)
  }

  unknown_cols <- setdiff(names(row), ALL_COLUMNS)
  for (name in unknown_cols) add(name, "ERROR", row[[name]], "not a table column")

  for (name in names(DEPRECATED_COLUMNS)) {
    val <- row[[name]]
    if (!is.null(val) && !identical(val, NA) && !identical(val, "")) {
      add(name, "ERROR", val, sprintf("deprecated - %s", DEPRECATED_COLUMNS[[name]]))
    }
  }

  for (name in names(STRING_MAX_SIZE)) {
    val <- row[[name]]
    if (!is.null(val) && !identical(val, NA) && nchar(val) > STRING_MAX_SIZE[[name]]) {
      add(name, "ERROR", val, sprintf("exceeds max length %d", STRING_MAX_SIZE[[name]]))
    }
  }

  description <- row[["Study_Description"]]
  if (!is.null(description) && !identical(description, NA)) {
    if (nchar(description) > STUDY_DESCRIPTION_MAX_SIZE) {
      add("Study_Description", "ERROR", description,
          sprintf("exceeds SOP max of %d characters (%d chars)", STUDY_DESCRIPTION_MAX_SIZE, nchar(description)))
    }
    if (!startsWith(description, "This study provides")) {
      add("Study_Description", "WARNING", description,
          "should start with 'This study provides...' per SOP")
    }
  }

  for (name in names(LIST_COLUMNS)) {
    val <- row[[name]]
    if (!is.null(val) && !identical(val, NA) && length(val) > LIST_COLUMNS[[name]]) {
      add(name, "ERROR", val, sprintf("has %d items, max is %d", length(val), LIST_COLUMNS[[name]]))
    }
  }

  study_type <- row[["Study_Type"]]
  if (!is.null(study_type) && !identical(study_type, NA) &&
      !(study_type %in% ENUM_VALUES$Study_Type)) {
    add("Study_Type", "ERROR", study_type,
        sprintf("must be one of %s", paste(ENUM_VALUES$Study_Type, collapse = "/")))
  }

  for (name in BOOLEAN_COLUMNS) {
    val <- row[[name]]
    if (!is.null(val) && !identical(val, NA) && !is.logical(val)) {
      add(name, "ERROR", val, sprintf("must be TRUE/FALSE, got %s", class(val)))
    }
  }

  for (name in ENTITY_COLUMNS) {
    val <- row[[name]]
    if (!is.null(val) && !identical(val, NA) && !startsWith(val, "syn")) {
      add(name, "ERROR", val, "must be a Synapse entity ID (e.g. 'syn12345')")
    }
  }

  if (!is.null(valid_programs)) {
    programs <- row[["Program"]]
    if (!is.null(programs) && !identical(programs, NA)) {
      bad <- setdiff(programs, valid_programs)
      for (p in bad) {
        add("Program", "ERROR", p,
            sprintf("not in the ADKP Programs table (%s) - check spelling or add it there first", PROGRAMS_TABLE_ID))
      }
    }
  }

  specimen <- row[["specimenType"]]
  if (!is.null(specimen) && !identical(specimen, NA)) {
    for (v in setdiff(specimen, SPECIMEN_TYPE_VALUES)) {
      add("specimenType", "WARNING", v,
          "not in the SOP's known list - if genuinely new, draw the term from the data model's organ/tissue vocab")
    }
  }

  species <- row[["Species"]]
  if (!is.null(species) && !identical(species, NA)) {
    for (v in setdiff(species, SPECIES_VALUES)) {
      add("Species", "WARNING", v,
          sprintf("not in the SOP's official list (%s)", paste(SPECIES_VALUES, collapse = ", ")))
    }
  }

  grants <- row[["Grant Number"]]
  if (!is.null(grants) && !identical(grants, NA)) {
    for (g in grants) {
      if (grepl(.NIH_GRANT_CORE_RE, g) && (grepl("^[0-9]", g) || grepl("-", g))) {
        add("Grant Number", "WARNING", g,
            "looks like it still has an application type prefix or extension suffix - trim to activity code through serial number (e.g. 'R01AG046171')")
      }
    }
  }

  ref_checks <- list(
    ackContext = ACK_CONTEXT_VALUES,
    studyMetadata = STUDY_METADATA_VALUES,
    accessReqs = ACCESS_REQS_VALUES
  )
  for (name in names(ref_checks)) {
    val <- row[[name]]
    if (!is.null(val) && !identical(val, NA) && !(val %in% ref_checks[[name]])) {
      add(name, "WARNING", val,
          sprintf("doesn't match one of the SOP's known reference IDs (%s) - confirm this is intentional",
                  paste(ref_checks[[name]], collapse = ", ")))
    }
  }

  acknowledgement <- row[["Acknowledgement"]]
  if (!is.null(acknowledgement) && !identical(acknowledgement, NA) &&
      !grepl("^syn[0-9]+/wiki/[0-9]+$", acknowledgement)) {
    add("Acknowledgement", "WARNING", acknowledgement,
        "doesn't match the expected '<synID>/wiki/<subpage id>' format")
  }

  if (!is.null(known_values)) {
    for (name in names(known_values)) {
      values <- row[[name]]
      if (!is.null(values) && !identical(values, NA)) {
        for (v in setdiff(values, known_values[[name]])) {
          add(name, "WARNING", v, "not among existing values in the table - double check spelling/consistency")
        }
      }
    }
  }

  if (length(issues) == 0) {
    return(data.frame(column = character(), level = character(), value = character(),
                       message = character(), stringsAsFactors = FALSE))
  }
  do.call(rbind, issues)
}

validate_row <- function(row, known_values = NULL, valid_programs = NULL) {
  # Raises on the first ERROR-level issue; warns (via base R warning()) on any
  # WARNING-level issues. For a full table of every issue at once (nothing
  # raised), use validate_row_report() instead.
  issues <- .collect_issues(row, known_values = known_values, valid_programs = valid_programs)
  errors <- issues[issues$level == "ERROR", , drop = FALSE]
  if (nrow(errors) > 0) {
    stop(sprintf("%s: %s (value: %s)", errors$column[1], errors$message[1], errors$value[1]))
  }
  warnings <- issues[issues$level == "WARNING", , drop = FALSE]
  if (nrow(warnings) > 0) {
    for (i in seq_len(nrow(warnings))) {
      warning(sprintf("%s = '%s' - %s", warnings$column[i], warnings$value[i], warnings$message[i]))
    }
  }
  invisible(TRUE)
}

validate_row_report <- function(row, known_values = NULL, valid_programs = NULL) {
  # Same checks as validate_row(), but returns every issue as a data.frame
  # (columns: column, level, value, message) instead of stopping or warning.
  # Zero rows means the row is clean.
  .collect_issues(row, known_values = known_values, valid_programs = valid_programs)
}

validate_rows_report <- function(rows, known_values = NULL, valid_programs = NULL) {
  # Same as validate_row_report(), but for a list of row lists - adds a row_index column.
  reports <- lapply(seq_along(rows), function(i) {
    df <- validate_row_report(rows[[i]], known_values = known_values, valid_programs = valid_programs)
    if (nrow(df) > 0) df$row_index <- i
    df
  })
  reports <- reports[vapply(reports, nrow, integer(1)) > 0]
  if (length(reports) == 0) {
    return(data.frame(row_index = integer(), column = character(), level = character(),
                       value = character(), message = character(), stringsAsFactors = FALSE))
  }
  result <- do.call(rbind, reports)
  result[, c("row_index", "column", "level", "value", "message")]
}

add_study_row <- function(row, known_values = NULL, valid_programs = NULL) {
  validate_row(row, known_values = known_values, valid_programs = valid_programs)
  # Build via setNames(lapply(...)), NOT row[ALL_COLUMNS]: subsetting a list by a
  # name it doesn't contain (e.g. a row missing the deprecated "Citations" key)
  # gives that slot the name NA instead of the requested name - confirmed against
  # real data on 2026-08-26, it turns into a garbage "NA." column downstream.
  ordered <- setNames(lapply(ALL_COLUMNS, function(col) row[[col]]), ALL_COLUMNS)
  df <- as.data.frame(
    lapply(ordered, function(x) if (is.null(x)) NA else x[[1]]),
    stringsAsFactors = FALSE,
    check.names = FALSE  # otherwise "Grant Number" is sanitized to "Grant.Number",
                          # and the list-column loop below (which looks it up by its
                          # real name) creates a stray duplicate column instead of
                          # overwriting it - also confirmed against real data.
  )
  # STRING_LIST columns must be JSON-encoded strings, not R list-columns - see
  # the note at the top of this file. as.list() before toJSON() is required:
  # toJSON() on a plain length-1 character vector emits a bare JSON string
  # ("MODEL-AD"), not an array (["MODEL-AD"]), which Synapse also rejects -
  # confirmed against real data on 2026-08-26.
  for (name in names(LIST_COLUMNS)) {
    if (!is.null(row[[name]]) && !identical(row[[name]], NA)) {
      df[[name]] <- rjson::toJSON(as.list(unlist(row[[name]])))
    }
  }
  table <- Table(STUDIES_TABLE_ID, df)
  synStore(table)
}

update_study_row <- function(row_id, updates) {
  query <- synTableQuery(sprintf("SELECT * FROM %s WHERE ROW_ID = %d", STUDIES_TABLE_ID, row_id))
  df <- as.data.frame(query)
  if (nrow(df) == 0) {
    stop(sprintf("No row found with ROW_ID=%d", row_id))
  }
  # Untouched STRING_LIST columns come back from the query already as the
  # JSON-string text Table()/synStore() expects on write (see the note at the
  # top of this file) - leave them as-is. Only a column actually present in
  # `updates` needs handling: if it's a STRING_LIST column, JSON-encode the
  # given R list/vector before assigning; otherwise assign it directly.
  for (col in names(updates)) {
    value <- updates[[col]]
    if (col %in% names(LIST_COLUMNS)) {
      value <- rjson::toJSON(as.list(unlist(value)))
    }
    df[[col]][[1]] <- value
  }
  table <- Table(STUDIES_TABLE_ID, df)
  synStore(table)
}

find_study_row_id <- function(study_abbreviation) {
  # Looks up the ROW_ID of the existing row for a study, by its Study_Abbreviation,
  # for use with update_study_row(). Errors if zero or more than one row matches.
  query <- synTableQuery(sprintf(
    "SELECT ROW_ID FROM %s WHERE Study_Abbreviation = '%s'", STUDIES_TABLE_ID, study_abbreviation
  ))
  # suppressWarnings: synapser's own CSV-to-dataframe conversion emits a benign
  # "longer argument not a multiple of length of shorter" warning for this
  # narrow a query (confirmed via traceback on 2026-08-26 - it's internal to
  # synapser:::.convertToRTypeFromSchema, not a sign anything here is wrong).
  df <- suppressWarnings(as.data.frame(query))
  if (nrow(df) == 0) {
    stop(sprintf("No row found with Study_Abbreviation = '%s'", study_abbreviation))
  }
  if (nrow(df) > 1) {
    stop(sprintf(
      "Multiple rows found with Study_Abbreviation = '%s' (ROW_IDs: %s) - use update_study_row() directly with the correct ROW_ID",
      study_abbreviation, paste(df$ROW_ID, collapse = ", ")
    ))
  }
  as.integer(df$ROW_ID[1])
}

# ==============================================================================
# Runs automatically when this file is sourced or Rscript'd, using MODE,
# STUDY_ROW/STUDY_UPDATES, and DRY_RUN from the top of the file.
# ==============================================================================

login_synapse()
known <- get_known_values()
programs <- get_valid_programs()

if (!(MODE %in% c("add", "update"))) {
  stop(sprintf("MODE must be 'add' or 'update', got '%s'", MODE))
}

if (MODE == "add") {
  report <- validate_row_report(STUDY_ROW, known_values = known, valid_programs = programs)
  if (nrow(report) == 0) {
    cat("No issues found.\n")
  } else {
    print(report, row.names = FALSE)
  }

  has_errors <- nrow(report) > 0 && any(report$level == "ERROR")

  if (DRY_RUN) {
    cat("\nDRY_RUN is TRUE - nothing was submitted. Set DRY_RUN <- FALSE at the top of ",
        "this file to submit STUDY_ROW as a new row once the report above looks right.\n", sep = "")
  } else if (has_errors) {
    cat("\nNot submitting: fix the ERROR-level issue(s) above first.\n")
  } else {
    add_study_row(STUDY_ROW, known_values = known, valid_programs = programs)
    cat("\nRow submitted to the ADKP Portal Studies Table.\n")
  }
} else {
  row_id <- find_study_row_id(UPDATE_STUDY_ABBREVIATION)
  cat(sprintf("Found ROW_ID %d for Study_Abbreviation = '%s'.\n", row_id, UPDATE_STUDY_ABBREVIATION))

  report <- validate_row_report(STUDY_UPDATES, known_values = known, valid_programs = programs)
  if (nrow(report) == 0) {
    cat("No issues found.\n")
  } else {
    print(report, row.names = FALSE)
  }

  has_errors <- nrow(report) > 0 && any(report$level == "ERROR")

  if (DRY_RUN) {
    cat("\nDRY_RUN is TRUE - nothing was updated. Set DRY_RUN <- FALSE at the top of ",
        sprintf("this file to apply STUDY_UPDATES to ROW_ID %d once the report above looks right.\n", row_id), sep = "")
  } else if (has_errors) {
    cat("\nNot updating: fix the ERROR-level issue(s) above first.\n")
  } else {
    update_study_row(row_id, STUDY_UPDATES)
    cat(sprintf("\nROW_ID %d updated in the ADKP Portal Studies Table.\n", row_id))
  }
}
