#!/usr/bin/env Rscript
# Extracts the "must stay in sync" constants from portal-studies-table/r/adkp_studies_table.R
# and prints them as a single JSON object to stdout. Used by
# portal-studies-table/scripts/check_sync.py to verify the R and Python
# versions of the ADKP Portal Studies Table tool haven't drifted apart.
#
# Deliberately does NOT require synapser (or the Python bridge it needs) - it
# strips the library(synapser) line and everything from the auto-run block
# onward before sourcing, so it never touches Synapse. Only needs base R plus
# the lightweight, pure-R "rjson" package.

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1) {
  stop("Usage: Rscript dump_r_constants.R <path-to-adkp_studies_table.R>")
}
r_file <- args[[1]]

code <- readLines(r_file)
code <- code[!grepl("^library\\(synapser\\)", code)]

# Cut everything from the auto-run block onward (that's the first line that
# actually executes against Synapse) - keep the cut point tied to that literal
# call rather than the comments above it, so wording tweaks to the divider
# comments can't silently break this script.
cut_at <- grep("^login_synapse\\(\\)$", code)[1]
if (!is.na(cut_at)) {
  code <- code[seq_len(cut_at - 1)]
}

eval(parse(text = paste(code, collapse = "\n")), envir = globalenv())

KEYS <- c(
  "STUDIES_TABLE_ID", "PROGRAMS_TABLE_ID", "ALL_COLUMNS", "STRING_MAX_SIZE",
  "STUDY_DESCRIPTION_MAX_SIZE", "DEPRECATED_COLUMNS", "COLUMN_NOTES", "ENUM_VALUES",
  "SPECIMEN_TYPE_VALUES", "SPECIES_VALUES",
  "ACK_CONTEXT_STANDARD", "ACK_CONTEXT_REPROCESSED", "ACK_CONTEXT_UCI_CLU_H2KBKI", "ACK_CONTEXT_VALUES",
  "STUDY_METADATA_STANDARD", "STUDY_METADATA_ADNI", "STUDY_METADATA_ROSMAP",
  "STUDY_METADATA_MAYORNASEQ", "STUDY_METADATA_MSBB", "STUDY_METADATA_VALUES",
  "ACCESS_REQS_CONTROLLED", "ACCESS_REQS_OPEN", "ACCESS_REQS_ADNI", "ACCESS_REQS_FRAMINGHAM", "ACCESS_REQS_VALUES",
  "LIST_COLUMNS", "BOOLEAN_COLUMNS", "ENTITY_COLUMNS"
)

# rjson::toJSON renders a length-1 atomic vector as a bare JSON scalar (e.g.
# "Study") rather than an array (["Study"]), even though these keys are
# conceptually lists/arrays - confirmed against a live comparison on
# 2026-08-26 (ENTITY_COLUMNS <- c("Study") round-tripped as "Study", not
# ["Study"], causing a false mismatch against Python's ["Study"]). as.list()
# forces these to always serialize as arrays, matching Python's list type.
ARRAY_KEYS <- c(
  "ALL_COLUMNS", "SPECIMEN_TYPE_VALUES", "SPECIES_VALUES", "ACK_CONTEXT_VALUES",
  "STUDY_METADATA_VALUES", "ACCESS_REQS_VALUES", "BOOLEAN_COLUMNS", "ENTITY_COLUMNS"
)

result <- setNames(lapply(KEYS, function(k) {
  value <- get(k, envir = globalenv())
  if (k %in% ARRAY_KEYS) as.list(value) else value
}), KEYS)
cat(rjson::toJSON(result))
