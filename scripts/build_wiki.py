#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

"""Build wiki pages from generated and hand-written docs.

Hand-written pages live in src/docs/; generated pages (shell reference,
Python API docs) are built into docs/ by the normal build targets.  This
script merges both sets and transforms them into a flat structure suitable
for a GitHub wiki, rewriting internal links and generating a _Sidebar.md.

Usage:
    ./scripts/build_wiki.py [--out DIR]

The output directory defaults to 'wiki/' in the repository root.
"""

import argparse
import os
import re
import shutil
import sys

REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))

# Hand-written pages (relative to src/docs/) -> wiki name
HANDWRITTEN_PAGES = {
    "index.md": "Home.md",
    "ishfiles.md": "ishfiles.md",
}

# Generated pages (relative to docs/) -> wiki name
GENERATED_PAGES = {
    "ishlib_shell.md": "ishlib_shell.md",
    "pyishlib/index.md": "pyishlib.md",
}

PYISHLIB_PREFIX = "pyishlib-"


def discover_pyishlib_pages(docs_dir):
    """Find all pyishlib subpages and return their mapping."""
    mapping = {}
    pydir = os.path.join(docs_dir, "pyishlib")
    if not os.path.isdir(pydir):
        return mapping
    for name in sorted(os.listdir(pydir)):
        if name.endswith(".md") and name != "index.md":
            src = f"pyishlib/{name}"
            mapping[src] = f"{PYISHLIB_PREFIX}{name}"
    return mapping


def collect_pages(src_docs_dir, gen_docs_dir):
    """Collect all pages with their absolute source paths and wiki names."""
    pages = []  # list of (abs_path, relative_key, wiki_name)

    for rel, wiki_name in HANDWRITTEN_PAGES.items():
        pages.append((os.path.join(src_docs_dir, rel), rel, wiki_name))

    for rel, wiki_name in GENERATED_PAGES.items():
        pages.append((os.path.join(gen_docs_dir, rel), rel, wiki_name))

    pyishlib_pages = discover_pyishlib_pages(gen_docs_dir)
    for rel, wiki_name in pyishlib_pages.items():
        pages.append((os.path.join(gen_docs_dir, rel), rel, wiki_name))

    return pages


def build_link_rewrite_map(pages):
    """Build a dict mapping old link targets to new wiki page names."""
    rewrites = {}
    for _, rel, wiki_name in pages:
        rewrites[rel] = wiki_name
        if rel.startswith("pyishlib/"):
            rewrites[os.path.basename(rel)] = wiki_name
    return rewrites


def rewrite_links(content, rewrites):
    """Rewrite markdown links to point to wiki page names."""

    def replace_link(match):
        prefix = match.group(1)
        target = match.group(2)
        suffix = match.group(3)

        anchor = ""
        if "#" in target:
            target, anchor = target.split("#", 1)
            anchor = "#" + anchor

        if target in rewrites:
            return f"{prefix}{rewrites[target]}{anchor}{suffix}"

        return match.group(0)

    return re.sub(
        r"(\[(?:[^\]]*)\]\()([^)]+?)(\))",
        replace_link,
        content,
    )


def _safe_rmtree(out_dir):
    """Remove out_dir with a safety check against dangerous paths."""
    real = os.path.realpath(out_dir)
    if real in ("/", os.path.expanduser("~"), REPO_ROOT):
        print(f"Error: refusing to delete {real} (safety guard)", file=sys.stderr)
        sys.exit(1)
    shutil.rmtree(real)


def build_wiki(src_docs_dir, gen_docs_dir, out_dir):
    """Copy and transform docs into wiki format."""
    pages = collect_pages(src_docs_dir, gen_docs_dir)
    rewrites = build_link_rewrite_map(pages)

    if os.path.exists(out_dir):
        _safe_rmtree(out_dir)
    os.makedirs(out_dir)

    for src_path, _, wiki_name in pages:
        if not os.path.isfile(src_path):
            print(f"Warning: {src_path} not found, skipping", file=sys.stderr)
            continue

        with open(src_path, "r", encoding="utf-8") as f:
            content = f.read()

        content = rewrite_links(content, rewrites)

        dest_path = os.path.join(out_dir, wiki_name)
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(content)

    sidebar = build_sidebar(pages)
    with open(os.path.join(out_dir, "_Sidebar.md"), "w", encoding="utf-8") as f:
        f.write(sidebar)

    print(f"Wiki pages written to {out_dir}/")
    for _, _, wiki_name in sorted(pages, key=lambda p: p[2]):
        print(f"  {wiki_name}")
    print("  _Sidebar.md")


def build_sidebar(pages):
    """Generate a _Sidebar.md for wiki navigation."""
    lines = [
        "### ishlib",
        "",
        "- [[Home]]",
        "- [[Shell Library|ishlib_shell]]",
        "- [[ishfiles CLI|ishfiles]]",
        "- [[Python Library|pyishlib]]",
    ]

    pyishlib_pages = sorted(
        (rel, wiki_name)
        for _, rel, wiki_name in pages
        if rel.startswith("pyishlib/") and rel != "pyishlib/index.md"
    )
    if pyishlib_pages:
        lines.append("")
        lines.append("#### Python Modules")
        lines.append("")
        for rel, wiki_name in pyishlib_pages:
            module_name = os.path.basename(rel).replace(".md", "")
            page_name = wiki_name.replace(".md", "")
            lines.append(f"  - [[{module_name}|{page_name}]]")

    lines.append("")
    return "\n".join(lines)


def main():
    """Parse arguments and build wiki pages."""
    parser = argparse.ArgumentParser(description="Build wiki pages from docs")
    parser.add_argument(
        "--out",
        default=os.path.join(REPO_ROOT, "wiki"),
        help="Output directory (default: wiki/)",
    )
    parser.add_argument(
        "--src-docs-dir",
        default=os.path.join(REPO_ROOT, "src", "docs"),
        help="Hand-written docs directory (default: src/docs/)",
    )
    parser.add_argument(
        "--gen-docs-dir",
        default=os.path.join(REPO_ROOT, "docs"),
        help="Generated docs directory (default: docs/)",
    )
    args = parser.parse_args()

    src_docs_dir = os.path.realpath(args.src_docs_dir)
    gen_docs_dir = os.path.realpath(args.gen_docs_dir)
    out_dir = os.path.realpath(args.out)

    if not os.path.isdir(src_docs_dir):
        print(f"Error: src docs directory not found: {src_docs_dir}", file=sys.stderr)
        sys.exit(1)

    build_wiki(src_docs_dir, gen_docs_dir, out_dir)


if __name__ == "__main__":
    main()
