#!/usr/bin/env python3
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

"""Build wiki pages from generated docs.

Copies and transforms documentation files from docs/ into a flat structure
suitable for a GitHub wiki. Pyishlib subpages are flattened with a 'pyishlib-'
prefix, and markdown links are rewritten to match.

Usage:
    ./scripts/build_wiki.py [--out DIR]

The output directory defaults to 'wiki/' in the repository root.
"""

import argparse
import os
import re
import shutil
import sys

# Mapping of source paths (relative to docs/) to wiki page names.
# None means "derive automatically" (used for pyishlib subpages).
PAGE_MAP = {
    "index.md": "Home.md",
    "ishlib_shell.md": "ishlib_shell.md",
    "ishfiles.md": "ishfiles.md",
    "pyishlib/index.md": "pyishlib.md",
}

PYISHLIB_PREFIX = "pyishlib-"


def discover_pyishlib_pages(docs_dir):
    """Find all pyishlib subpages and add them to the page map."""
    mapping = dict(PAGE_MAP)
    pydir = os.path.join(docs_dir, "pyishlib")
    if not os.path.isdir(pydir):
        return mapping
    for name in sorted(os.listdir(pydir)):
        if name.endswith(".md") and name != "index.md":
            src = f"pyishlib/{name}"
            mapping[src] = f"{PYISHLIB_PREFIX}{name}"
    return mapping


def build_link_rewrite_map(mapping):
    """Build a dict mapping old link targets to new wiki page names."""
    rewrites = {}
    for src, dest in mapping.items():
        # From docs root context
        rewrites[src] = dest
        # From pyishlib/ subdirectory context (relative links)
        if src.startswith("pyishlib/"):
            basename = os.path.basename(src)
            if basename == "index.md":
                rewrites[basename] = dest  # only for pyishlib context
            else:
                rewrites[basename] = dest
    return rewrites


def rewrite_links(content, rewrites, source_in_pyishlib):
    """Rewrite markdown links to point to wiki page names."""
    def replace_link(match):
        prefix = match.group(1)  # [text]( or [[
        target = match.group(2)
        suffix = match.group(3)  # ) or ]]

        # Strip anchor
        anchor = ""
        if "#" in target:
            target, anchor = target.split("#", 1)
            anchor = "#" + anchor

        # Handle relative links from pyishlib subpages
        if source_in_pyishlib and target in rewrites:
            return f"{prefix}{rewrites[target]}{anchor}{suffix}"

        # Handle links from root-level pages
        if target in rewrites:
            return f"{prefix}{rewrites[target]}{anchor}{suffix}"

        # Handle pyishlib/ prefixed links from root pages
        if target.startswith("pyishlib/"):
            basename = os.path.basename(target)
            full_key = target
            if full_key in rewrites:
                return f"{prefix}{rewrites[full_key]}{anchor}{suffix}"

        return match.group(0)

    # Match [text](link) and [text](link#anchor)
    content = re.sub(
        r'(\[(?:[^\]]*)\]\()([^)]+?)(\))',
        replace_link,
        content,
    )
    return content


def build_wiki(docs_dir, out_dir):
    """Copy and transform docs into wiki format."""
    mapping = discover_pyishlib_pages(docs_dir)
    rewrites = build_link_rewrite_map(mapping)

    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    for src_rel, dest_name in mapping.items():
        src_path = os.path.join(docs_dir, src_rel)
        if not os.path.isfile(src_path):
            print(f"Warning: {src_path} not found, skipping", file=sys.stderr)
            continue

        with open(src_path, "r", encoding="utf-8") as f:
            content = f.read()

        in_pyishlib = src_rel.startswith("pyishlib/") and src_rel != "pyishlib/index.md"
        content = rewrite_links(content, rewrites, in_pyishlib)

        dest_path = os.path.join(out_dir, dest_name)
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(content)

    # Generate sidebar
    sidebar = build_sidebar(mapping)
    with open(os.path.join(out_dir, "_Sidebar.md"), "w", encoding="utf-8") as f:
        f.write(sidebar)

    print(f"Wiki pages written to {out_dir}/")
    for dest_name in sorted(mapping.values()):
        print(f"  {dest_name}")
    print(f"  _Sidebar.md")


def build_sidebar(mapping):
    """Generate a _Sidebar.md for wiki navigation."""
    lines = [
        "### ishlib",
        "",
        "- [[Home]]",
        "- [[Shell Library|ishlib_shell]]",
        "- [[ishfiles CLI|ishfiles]]",
        "- [[Python Library|pyishlib]]",
    ]

    # Add pyishlib subpages
    pyishlib_pages = sorted(
        (src, dest)
        for src, dest in mapping.items()
        if src.startswith("pyishlib/") and src != "pyishlib/index.md"
    )
    if pyishlib_pages:
        lines.append("")
        lines.append("#### Python Modules")
        lines.append("")
        for src, dest in pyishlib_pages:
            module_name = os.path.basename(src).replace(".md", "")
            wiki_name = dest.replace(".md", "")
            lines.append(f"  - [[{module_name}|{wiki_name}]]")

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Build wiki pages from docs")
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(__file__), "..", "wiki"),
        help="Output directory (default: wiki/)",
    )
    parser.add_argument(
        "--docs-dir",
        default=os.path.join(os.path.dirname(__file__), "..", "docs"),
        help="Docs source directory (default: docs/)",
    )
    args = parser.parse_args()

    docs_dir = os.path.realpath(args.docs_dir)
    out_dir = os.path.realpath(args.out)

    if not os.path.isdir(docs_dir):
        print(f"Error: docs directory not found: {docs_dir}", file=sys.stderr)
        sys.exit(1)

    build_wiki(docs_dir, out_dir)


if __name__ == "__main__":
    main()
