"""The results page must not say anything the repository does not.

Its problems log, bug-injection table and verification matrix are hand-written content, so each entry
carries a `source` quote. These tests fail if a quote no longer appears in the document it cites, or if
the system diagram names a file that does not exist.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "site-src" / "src" / "content"


def norm(text: str) -> str:
    """Strip markdown emphasis and code ticks, collapse whitespace, lower-case."""
    return re.sub(r"\s+", " ", re.sub(r"[*`_]", "", text)).strip().lower()


def load(name: str) -> list[dict]:
    return json.loads((CONTENT / name).read_text(encoding="utf-8"))


def doc(path: str) -> str:
    p = ROOT / path
    # docs/ is kept offline (git-ignored), so on a fresh clone or in CI there is nothing to check quotes against.
    if not (ROOT / "docs").is_dir():
        pytest.skip("docs/ is not in this checkout; quote checks run only where the docs exist")
    assert p.exists(), f"{path} is cited by the page but does not exist"
    return norm(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("item", load("problems.json"), ids=lambda i: i["id"])
def test_problem_is_in_the_build_log(item):
    assert norm(item["source"]) in doc("docs/06-build-log.md"), item["id"]


def test_problems_have_every_field_and_unique_ids():
    items = load("problems.json")
    assert len({i["id"] for i in items}) == len(items)
    for i in items:
        for k in ("title", "symptom", "wrong_model", "cause", "fix", "lesson", "evidence", "when", "tag"):
            assert i[k].strip(), (i["id"], k)


@pytest.mark.parametrize("item", load("bugs.json"), ids=lambda i: i["source"][:30])
def test_bug_injection_row_is_in_the_correctness_doc(item):
    assert norm(item["source"]) in doc("docs/03-correctness.md")


@pytest.mark.parametrize("item", load("verification.json"), ids=lambda i: i["claim"][:40])
def test_verification_claim_is_in_its_document(item):
    assert norm(item["source"]) in doc(item.get("doc", "docs/07-operations.md"))


def test_verification_matrix_has_both_kinds():
    statuses = {i["status"] for i in load("verification.json")}
    assert statuses == {"verified", "not-verified"}


def test_files_named_in_the_system_diagram_exist():
    src = (CONTENT / "architecture.ts").read_text(encoding="utf-8")
    files = re.findall(r"files: \[([^\]]*)\]", src)
    paths = [p for block in files for p in re.findall(r"'([^']+)'", block)]
    assert len(paths) >= 15
    missing = [p for p in paths if not (ROOT / p).exists()]
    assert missing == []
