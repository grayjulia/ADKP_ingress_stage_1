"""
Reusable template for creating and updating Synapse Wiki pages (root pages and
sub-pages) for the ADKP backend, while preserving contributor-submitted HTML
formatting (links, <sup>, <sub>, etc.) exactly as written.

Based on the synapseclient `WikiPage` model (synapseclient.models.wiki), per
the official tutorial (https://python-docs.synapse.org/en/stable/tutorials/python/wiki/,
fetched 2026-09-21) and the installed synapseclient==4.11.0 source
(site-packages/synapseclient/models/wiki.py, read 2026-09-21).

HOW FORMATTING IS PRESERVED
    `WikiPage.markdown` accepts either an inline string or a path to a file on
    disk. When given a file path, the client gzips the file's raw bytes and
    uploads them as-is - there is no markdown escaping, HTML escaping, or
    text-mode re-encoding in between. This template always passes a FILE PATH
    (never an inline string) for exactly that reason: it's the only mode that
    guarantees byte-for-byte preservation of the contributor's original HTML
    (their <a href>, <sup>, <sub>, etc. tags survive untouched).

    Do not run the contributor's content through html.escape(), markdown
    conversion, or string manipulation of any kind before saving it to the
    content file - edit the file directly if changes are needed.

    Synapse's wiki renderer does apply its own server-side HTML sanitizer
    when the page is rendered (this is server behavior we can't inspect or
    reproduce from the client). Standard inline tags like <a>, <sup>, <sub>,
    <b>, <i>, <u>, <span> are expected to pass through and render correctly,
    but always spot-check the rendered page in the Synapse UI after the
    first upload of a new content pattern. verify_wiki_markdown() below only
    confirms the client didn't corrupt anything in transit/storage - it
    can't confirm how the renderer will display it.

Setup:
    pip install -r requirements.txt
    Authenticate once via `synapse config` (~/.synapseConfig) or by setting the
    SYNAPSE_AUTH_TOKEN env var to a personal access token - do not hardcode
    credentials in this file.

Use as a library:
    from adkp_wiki_template import login, create_or_update_wiki

    syn = login()

    # Preview first: opens the content file in your browser and prints the
    # create/update plan, writes nothing to Synapse.
    create_or_update_wiki(
        syn,
        owner_id="syn00000000",
        title="Acknowledgement - EXAMPLE",
        content_path="acknowledgement_example.html",
        parent_id="00000000",  # only used when creating a brand-new page
        dry_run=True,
    )

    # Looks right -> push for real.
    create_or_update_wiki(
        syn, owner_id="syn00000000", title="Acknowledgement - EXAMPLE",
        content_path="acknowledgement_example.html", parent_id="00000000",
    )

Or from the command line:
    python adkp_wiki_template.py syn00000000 "Acknowledgement - EXAMPLE" \\
        acknowledgement_example.html --parent-id 00000000 --dry-run

GETTING A CONTENT FILE FROM A CONTRIBUTOR'S JIRA TICKET
    Contributors often submit this text as a Jira ticket field rather than a
    ready-made HTML file. Three ways to turn that into a content file, in
    order of preference:

    1. Jira REST API (best fidelity, no copy-paste) - see
       fetch_jira_rendered_fields() below. Pulls the field's server-rendered
       HTML directly - the same markup Jira itself displays - straight to a
       file. Needs a Jira API token.

    2. Browser DevTools copy (best fidelity without an API token) - open the
       ticket, right-click the rendered field -> Inspect -> in the Elements
       panel right-click the containing element -> Copy -> Copy outerHTML.
       Paste that into a .html file. Captures exactly what Jira rendered.

    3. Word or Google Docs round-trip (fallback - needs cleanup) - paste the
       rendered ticket text into Word or Google Docs, then:
         - Word: File -> Save As -> Web Page (.htm)
         - Google Docs: File -> Download -> Web Page (.html, zipped)
       Both convert superscript/subscript/links to real HTML tags, but both
       also inject wrapper markup (Word: `mso-*` styles and XML namespaces;
       Docs: inline `<span style="...">` clutter) that should be stripped
       before use, and Word's autocorrect can silently swap characters
       (straight quotes -> curly, hyphens -> em dashes) including inside
       URLs. Diff the result against the original ticket text before trusting
       it, and prefer option 1 or 2 whenever either is available.

    Whichever method produces the file, run create_or_update_wiki() with
    verify=True (the default) and then spot-check the rendered page in the
    Synapse UI - see the HOW FORMATTING IS PRESERVED note above for why that
    manual check still matters even after verification passes.
"""

import argparse
import hashlib
import os
import tempfile

import synapseclient
from synapseclient.core.exceptions import SynapseHTTPError
from synapseclient.models import WikiPage


def login(auth_token=None):
    """Log in to Synapse. Falls back to ~/.synapseConfig / SYNAPSE_AUTH_TOKEN if auth_token is None."""
    syn = synapseclient.Synapse()
    syn.login(authToken=auth_token)
    return syn


def find_existing_wiki(syn, owner_id, title):
    """
    Look up an existing wiki page (root or sub-page) on `owner_id` by exact
    title match, searching the whole wiki tree for that owner. Returns the
    matching WikiPage (with .id populated), or None if no wiki page with that
    title exists yet (including the case where the owner has no wiki at all).
    """
    try:
        return WikiPage(owner_id=owner_id, title=title).get(synapse_client=syn)
    except ValueError:
        # WikiPage.get() raises ValueError when the header tree has no page
        # matching this title (but the owner has at least one wiki page).
        return None
    except SynapseHTTPError as e:
        # Raised when the owner has no wiki page at all yet (404 on the
        # underlying header-tree lookup).
        if getattr(e, "response", None) is not None and e.response.status_code == 404:
            return None
        raise


def heading_html(text, level=2, bold=True):
    """
    Build a simple HTML heading snippet for a section title within wiki
    content - e.g. to turn a plain-text field label like "Disease focus."
    into a bold, larger sub-heading before saving it to a content file.

    `level` is an HTML heading level, 1 (largest) through 6 (smallest).
    `bold` additionally wraps the text in <strong>, so it stays bold even if
    a wiki's stylesheet ever overrides heading weight.

    This returns a snippet, not a full page - insert it into the content
    file where you want the heading to appear (e.g. via find/replace on the
    plain-text label, or by prepending it before you write the file).
    """
    if not 1 <= level <= 6:
        raise ValueError("level must be between 1 and 6")
    inner = f"<strong>{text}</strong>" if bold else text
    return f"<h{level}>{inner}</h{level}>"


def preview_content(content_path):
    """
    Open a content file directly in the default web browser, so you can
    visually check bold/heading/superscript/subscript/link formatting before
    it's pushed to Synapse. This renders the raw HTML as a browser sees it,
    which is a useful sanity check but won't exactly match Synapse's own
    wiki theme/CSS - it confirms the tags are structured the way you intend,
    not the final on-page appearance.
    """
    import webbrowser

    path = os.path.abspath(content_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Content file not found: {content_path}")
    webbrowser.open(f"file://{path}")
    return path


def create_or_update_wiki(syn, owner_id, title, content_path, parent_id=None, verify=True, dry_run=False):
    """
    Create a new wiki page, or update it in place if a page with this exact
    title already exists on this owner. `content_path` must be a path to a
    file on disk (not an inline string) so its contents are uploaded
    byte-for-byte - see the module docstring.

    `parent_id` only matters for a brand-new page: leave it None for the
    owner's root wiki page, or set it to an existing page's id to create a
    new sub-page nested under it. It's ignored (the page's real parent is
    preserved) when updating an existing page.

    `dry_run=True` prints the create-vs-update plan, opens the content file
    in your browser for a visual check (see preview_content()), and returns
    None WITHOUT writing anything to Synapse. Run it this way first; rerun
    with dry_run=False once the preview looks right.

    Returns the stored WikiPage (or None if dry_run). Raises
    FileNotFoundError if content_path doesn't exist.
    """
    if not os.path.isfile(content_path):
        raise FileNotFoundError(f"Content file not found: {content_path}")

    existing = find_existing_wiki(syn, owner_id, title)

    if dry_run:
        if existing:
            print(f"[DRY RUN] Would UPDATE wiki page {existing.id!r} ('{title}') on {owner_id}.")
        elif parent_id:
            print(f"[DRY RUN] Would CREATE new sub-page ('{title}') under {parent_id} on {owner_id}.")
        else:
            print(f"[DRY RUN] Would CREATE ('{title}') as the root wiki page of {owner_id}.")
        print(f"Content file: {os.path.abspath(content_path)}")
        preview_content(content_path)
        print("Nothing was written to Synapse. Rerun with dry_run=False to push this.")
        return None

    if existing:
        wiki = WikiPage(owner_id=owner_id, id=existing.id, title=title, markdown=content_path)
        action = "Updated"
    else:
        wiki = WikiPage(owner_id=owner_id, title=title, markdown=content_path, parent_id=parent_id)
        action = "Created"

    stored = wiki.store(synapse_client=syn)
    print(f"{action} wiki page {stored.id!r} ('{title}') on {owner_id}.")
    print(f"View at: https://www.synapse.org/Synapse:{owner_id}/wiki/{stored.id}")

    if verify:
        verify_wiki_markdown(syn, owner_id, stored.id, content_path)

    return stored


def verify_wiki_markdown(syn, owner_id, wiki_id, local_content_path):
    """
    Re-download the markdown just stored on `wiki_id` and compare it
    byte-for-byte against the local content file, to confirm the client
    didn't alter anything in transit (encoding issues, truncation, etc.).
    This does NOT tell you how Synapse's renderer will display the HTML -
    always spot-check that separately in the Synapse UI.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        downloaded_path = WikiPage(owner_id=owner_id, id=wiki_id).get_markdown_file(
            download_file=True, download_location=tmp_dir, synapse_client=syn
        )
        with open(downloaded_path, "rb") as f:
            remote_bytes = f.read()

    with open(local_content_path, "rb") as f:
        local_bytes = f.read()

    if hashlib.sha256(remote_bytes).digest() == hashlib.sha256(local_bytes).digest():
        print("Verified: stored markdown matches the local content file exactly.")
        return True
    else:
        print("WARNING: stored markdown differs from the local content file - "
              "something altered it in transit. Compare the two files directly.")
        return False


def fetch_jira_rendered_fields(issue_key, field_ids, base_url="https://sagebionetworks.jira.com",
                                email=None, api_token=None):
    """
    Fetch one or more fields from a Jira issue as server-rendered HTML (the
    same HTML the Jira UI displays), via the REST API's `renderedFields`
    expansion. This is the highest-fidelity way to pull a contributor's
    ticket text into a wiki content file - it goes straight from Jira's own
    renderer to a file, with no clipboard/copy-paste step in between.

    Needs a Jira API token: https://id.atlassian.com/manage-profile/security/api-tokens
    Falls back to the JIRA_EMAIL / JIRA_API_TOKEN env vars if email/api_token
    aren't given - do not hardcode credentials in this file.

    Arguments:
        issue_key: e.g. "PROJ-123"
        field_ids: Jira field ids to fetch, e.g. ["customfield_10050"]. To find
            the field id for a given field label on your Jira instance, fetch
            any issue with expand="names" (or check your project's field
            configuration) and read off its `names` mapping - field ids are
            per-Jira-instance/project, not per-ticket, so look them up once
            and reuse them.
        base_url: the Jira Cloud site
        email, api_token: Jira Cloud API auth (HTTP Basic: email + token)

    Returns:
        dict of {field_id: rendered_html_string_or_None}. A None value means
        that field exists on the ticket but is empty/unpopulated.
    """
    import requests

    email = email or os.environ.get("JIRA_EMAIL")
    api_token = api_token or os.environ.get("JIRA_API_TOKEN")
    if not email or not api_token:
        raise ValueError(
            "Need a Jira email + API token - pass them in, or set the JIRA_EMAIL / "
            "JIRA_API_TOKEN env vars. Create a token at "
            "https://id.atlassian.com/manage-profile/security/api-tokens"
        )

    resp = requests.get(
        f"{base_url}/rest/api/3/issue/{issue_key}",
        params={"fields": ",".join(field_ids), "expand": "renderedFields"},
        auth=(email, api_token),
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    rendered = resp.json().get("renderedFields", {})
    return {field_id: rendered.get(field_id) for field_id in field_ids}


def save_jira_field(html, path):
    """
    Write a rendered-HTML field value (from fetch_jira_rendered_fields) to a
    content file exactly as returned - no reformatting. Raises ValueError if
    the field came back empty, so a blank ticket field can't silently produce
    a blank wiki page.
    """
    if not html:
        raise ValueError("No rendered content for this field - check it's actually populated on the ticket.")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    return path


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Create or update a Synapse wiki page (root or sub-page), "
                     "preserving contributor HTML formatting exactly."
    )
    parser.add_argument("owner_id", help="Synapse entity ID that owns the wiki (e.g. syn12345)")
    parser.add_argument("title", help="Wiki page title. Also used to find an existing page to update - "
                                       "keep titles unique/descriptive within an owner's wiki tree.")
    parser.add_argument("content_path", help="Path to the contributor's HTML/markdown content file")
    parser.add_argument("--parent-id", default=None,
                         help="Existing wiki page id to nest a NEW page under (ignored when updating "
                              "an existing page). Omit to create/update the owner's root wiki page.")
    parser.add_argument("--no-verify", action="store_true",
                         help="Skip re-downloading and byte-comparing the stored content after upload.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Preview only: print the create/update plan and open the content file in "
                              "your browser, but write nothing to Synapse.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    syn = login()
    create_or_update_wiki(
        syn,
        owner_id=args.owner_id,
        title=args.title,
        content_path=args.content_path,
        parent_id=args.parent_id,
        verify=not args.no_verify,
        dry_run=args.dry_run,
    )
