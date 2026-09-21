"""
Alphabetize the sub-pages under the Acknowledgment Statements wiki page
(wiki id 602387) in the AD Knowledge Portal project (syn12666371), without
disturbing the ordering of any other page in the tree.

This is a one-off, task-specific script (hardcoded to this owner/page) rather
than a general reusable tool - re-run it whenever an acknowledgement
statement is added to the Portal Studies Table, to re-sort the corresponding
wiki sub-pages.

Background: a Synapse project's wiki pages have a single tree-wide
`WikiOrderHint` (a flat `id_list` of every page id, in display order) rather
than a per-parent order field. To re-sort just one parent's children, you
have to find the contiguous slice of that list occupied by its current
children and replace only that slice - this script does that.

Setup:
    pip install -r requirements.txt   # synapseclient
    Authenticate once via `synapse config` (~/.synapseConfig) or by setting
    the SYNAPSE_AUTH_TOKEN env var to a personal access token - do not
    hardcode credentials in this file.

To use: run this file directly (`python alphabetize_acknowledgement_statements.py`).

Implementation note: use `syn.getWikiHeaders()` (hits the `/wikiheadertree`
endpoint) rather than the newer `synapseclient.models.WikiHeader.get()`
(hits `/wikiheadertree2`) - the v2 endpoint has been observed to lag behind
on very recently created pages, silently omitting them from the tree and
therefore from the re-sort.
"""

from synapseclient import Synapse
from synapseclient.models import WikiOrderHint

OWNER_ID = "syn12666371"
PARENT_WIKI_ID = "602387"  # "Acknowledgment Statements" page


def alphabetize_children(owner_id: str, parent_wiki_id: str) -> None:
    syn = Synapse()
    syn.login()

    headers = syn.getWikiHeaders(owner=owner_id)
    children = [h for h in headers if h.get("parentId") == parent_wiki_id]
    if not children:
        print(f"No children found under wiki id {parent_wiki_id} - nothing to do.")
        return

    order_hint = WikiOrderHint(owner_id=owner_id).get()
    id_list = order_hint.id_list

    child_ids = {h["id"] for h in children}
    title_by_id = {h["id"]: h["title"] for h in children}

    # Contiguous slice of id_list currently occupied by these children. Any
    # child missing from id_list entirely (e.g. a very recently created page
    # Synapse hasn't added to the order hint yet) is still included in the
    # sorted result and inserted into that slice.
    present_indices = sorted(i for i, wid in enumerate(id_list) if wid in child_ids)
    if not present_indices:
        print(f"None of {len(children)} children currently appear in the order hint - "
              "cannot determine where to splice the sorted block.")
        return
    lo, hi = present_indices[0], present_indices[-1]

    sorted_child_ids = sorted(child_ids, key=lambda wid: title_by_id[wid].strip().lower())

    order_hint.id_list = id_list[:lo] + sorted_child_ids + id_list[hi + 1:]
    order_hint.store()
    print(f"Stored new order for {len(sorted_child_ids)} sub-pages under wiki id {parent_wiki_id}.")


if __name__ == "__main__":
    alphabetize_children(owner_id=OWNER_ID, parent_wiki_id=PARENT_WIKI_ID)
