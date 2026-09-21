"""
Alphabetize the sub-pages under one wiki page in a Synapse project's wiki
tree, without disturbing the ordering of any other page in the tree.

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

To use: edit the CONFIG dict below (the only thing you should need to
change), then run this file directly (`python alphabetize_acknowledgement_statements.py`).
It always prints the current vs. proposed order for review; it only writes
to Synapse if CONFIG["dry_run"] is False.

Implementation note: use `syn.getWikiHeaders()` (hits the `/wikiheadertree`
endpoint) rather than the newer `synapseclient.models.WikiHeader.get()`
(hits `/wikiheadertree2`) - the v2 endpoint has been observed to lag behind
on very recently created pages, silently omitting them from the tree and
therefore from the re-sort.
"""

from synapseclient import Synapse
from synapseclient.models import WikiOrderHint

# ==============================================================================
# CONFIG - the only section you should need to edit.
# ==============================================================================

CONFIG = {
    "dry_run": True,  # True: only print the current vs. proposed order, change nothing.
                       # False: store the alphabetized order to Synapse.

    # The Synapse entity (usually a Project) that owns the wiki tree.
    "owner_id": "syn00000000",

    # The wiki page id whose direct children should be alphabetized by title.
    # Find this by inspecting syn.getWikiHeaders(owner=owner_id) - it's the
    # numeric "id" of the page whose sub-pages you want sorted, not its title.
    "parent_wiki_id": "000000",
}

# ==============================================================================
# Library code - shouldn't need to edit below this line.
# ==============================================================================


def alphabetize_children(owner_id: str, parent_wiki_id: str, dry_run: bool = True) -> None:
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

    current_titles = [title_by_id[wid] for wid in id_list[lo:hi + 1] if wid in title_by_id]
    proposed_titles = [title_by_id[wid] for wid in sorted_child_ids]

    print(f"{len(sorted_child_ids)} sub-pages under wiki id {parent_wiki_id}:\n")
    print("Current order:")
    for t in current_titles:
        print(f"  {t}")
    print("\nProposed (alphabetized) order:")
    for t in proposed_titles:
        print(f"  {t}")

    if dry_run:
        print("\nCONFIG['dry_run'] is True - nothing written. Set it to False to apply.")
        return

    order_hint.id_list = id_list[:lo] + sorted_child_ids + id_list[hi + 1:]
    order_hint.store()
    print(f"\nStored new order for {len(sorted_child_ids)} sub-pages under wiki id {parent_wiki_id}.")


if __name__ == "__main__":
    alphabetize_children(
        owner_id=CONFIG["owner_id"],
        parent_wiki_id=CONFIG["parent_wiki_id"],
        dry_run=CONFIG["dry_run"],
    )
