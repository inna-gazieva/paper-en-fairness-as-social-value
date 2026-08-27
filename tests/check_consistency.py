#!/usr/bin/env python3
"""Consistency self-check for this research repository.

Verifies that citation metadata files parse, that DOIs are consistent
between CITATION.cff and README.md, and that relative Markdown links
point to existing files. With --online, additionally checks that every
DOI mentioned in the repository resolves via doi.org.

Usage:
    python3 tests/check_consistency.py [--online]

Exit code 0 = OK (warnings possible), 1 = errors found.
No dependencies beyond the Python 3 standard library.
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>\)\]\}`*]+")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

errors = []
warnings = []


OWN_DOI_PREFIXES = ("10.5281/", "10.31235/")


def norm_doi(doi):
    doi = doi.rstrip(".,;:*/`")
    if doi.endswith(".svg"):  # DOI badge URL, not a DOI
        doi = doi[: -len(".svg")].rstrip(".")
    return doi


def find_dois(text):
    """DOI_RE plus extension across balanced parentheses (10.1016/S...(08)60108-2)."""
    out = []
    for m in DOI_RE.finditer(text):
        doi, end = m.group(0), m.end()
        while "(" in doi and doi.count("(") > doi.count(")") and end < len(text) and text[end] == ")":
            ext = re.match(r"\)[^\s\"'<>\]\}`*]*", text[end:])
            doi += ext.group(0)
            end += ext.end()
        out.append(norm_doi(doi))
    return out


def md_files():
    for p in sorted(ROOT.rglob("*.md")):
        if ".git" in p.parts or "node_modules" in p.parts:
            continue
        yield p


def check_citation_cff():
    p = ROOT / "CITATION.cff"
    if not p.exists():
        warnings.append("CITATION.cff is missing")
        return None
    text = p.read_text(encoding="utf-8")
    if not re.search(r"^title:", text, re.M):
        errors.append("CITATION.cff: no 'title' field")
    if "family-names" not in text and "given-names" not in text:
        errors.append("CITATION.cff: no author names")
    m = re.search(r"^doi:\s*[\"']?(10\.[^\s\"']+)", text, re.M)
    if not m:
        warnings.append("CITATION.cff: no top-level 'doi' field")
        return None
    return norm_doi(m.group(1))


def check_zenodo_json():
    p = ROOT / ".zenodo.json"
    if not p.exists():
        warnings.append(".zenodo.json is missing")
        return
    try:
        json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f".zenodo.json: invalid JSON ({e})")


def collect_dois():
    found = set()
    for p in md_files():
        found.update(find_dois(p.read_text(encoding="utf-8")))
    for name in ("CITATION.cff", ".zenodo.json", "codemeta.json"):
        p = ROOT / name
        if p.exists():
            found.update(find_dois(p.read_text(encoding="utf-8")))
    return found


def check_readme_has_cff_doi(cff_doi):
    readme = ROOT / "README.md"
    if not readme.exists():
        errors.append("README.md is missing")
        return
    if cff_doi and cff_doi not in readme.read_text(encoding="utf-8"):
        warnings.append(
            f"DOI from CITATION.cff ({cff_doi}) is not mentioned in README.md "
            "(concept vs version DOI? make sure this is intentional)"
        )


def check_relative_links():
    for p in md_files():
        text = p.read_text(encoding="utf-8")
        for m in LINK_RE.finditer(text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = urllib.parse.unquote(target.split("#")[0])
            if not target:
                continue
            if not (p.parent / target).exists():
                errors.append(f"{p.relative_to(ROOT)}: broken relative link -> {target}")


def check_dois_online(dois):
    def report(doi, detail, blocked=False):
        # Broken own identifiers (Zenodo, SocArXiv) are errors; rot in cited
        # bibliographies and anti-bot blocks are reported as warnings.
        if blocked:
            warnings.append(f"DOI could not be verified (site blocks bots): {doi} ({detail})")
        elif doi.startswith(OWN_DOI_PREFIXES):
            errors.append(f"own DOI does not resolve: {doi} ({detail})")
        else:
            warnings.append(f"cited DOI does not resolve: {doi} ({detail})")

    for doi in sorted(dois):
        url = "https://doi.org/" + urllib.parse.quote(doi, safe="/.()")
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "consistency-check/1.0"})
        try:
            urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as e:
            if e.code in (403, 405):
                try:
                    urllib.request.urlopen(
                        urllib.request.Request(url, headers={"User-Agent": "consistency-check/1.0"}),
                        timeout=15)
                    continue
                except urllib.error.HTTPError as e2:
                    report(doi, f"HTTP {e2.code}", blocked=(e2.code == 403))
                except Exception as e2:
                    report(doi, str(e2))
            else:
                report(doi, f"HTTP {e.code}")
        except Exception as e:
            warnings.append(f"DOI check skipped (network problem): {doi} ({e})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true",
                        help="also verify that every DOI resolves via doi.org")
    args = parser.parse_args()

    cff_doi = check_citation_cff()
    check_zenodo_json()
    check_readme_has_cff_doi(cff_doi)
    check_relative_links()
    dois = collect_dois()
    if args.online:
        check_dois_online(dois)

    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"\nChecked: {len(list(md_files()))} markdown files, {len(dois)} unique DOIs. "
          f"{len(errors)} error(s), {len(warnings)} warning(s).")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
