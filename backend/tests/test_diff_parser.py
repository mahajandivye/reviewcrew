"""Unit tests for the unified diff parser.

This module is the backbone of two features (inline comment anchors + the
Phase 4 diff viewer), so it gets the most thorough tests.
"""

from __future__ import annotations

from app.services.diff_parser import (
    added_lines_by_file,
    build_diff_text,
    commentable_lines_by_file,
    parse_unified_diff,
)

SAMPLE_DIFF = """diff --git a/app/services/checkout.py b/app/services/checkout.py
index 1111111..2222222 100644
--- a/app/services/checkout.py
+++ b/app/services/checkout.py
@@ -1,6 +1,8 @@
 from decimal import Decimal

 def apply_discount(total, percent):
-    if percent > 100:
-        percent = 100
-    return total - (total * Decimal(percent) / 100)
+    return total - (total * Decimal(percent) / 100)
+
+
+def charge_card(token, amount):
+    return amount
"""


def test_parses_file_path_and_hunk_header():
    files = parse_unified_diff(SAMPLE_DIFF)
    assert len(files) == 1

    parsed = files[0]
    assert parsed.path == "app/services/checkout.py"
    assert parsed.status == "modified"
    assert len(parsed.hunks) == 1
    assert parsed.hunks[0].old_start == 1
    assert parsed.hunks[0].new_start == 1


def test_added_lines_get_correct_new_line_numbers():
    parsed = parse_unified_diff(SAMPLE_DIFF)[0]
    added = parsed.added_lines

    # The three context lines occupy 1-3, so the first added line is 4.
    assert sorted(added) == [4, 5, 6, 7, 8]
    assert added[4] == "    return total - (total * Decimal(percent) / 100)"
    assert added[7] == "def charge_card(token, amount):"


def test_removed_lines_get_correct_old_line_numbers():
    parsed = parse_unified_diff(SAMPLE_DIFF)[0]
    assert sorted(parsed.removed_lines) == [4, 5, 6]


def test_commentable_lines_include_added_and_context():
    parsed = parse_unified_diff(SAMPLE_DIFF)[0]
    # Context lines 1-3 + added lines 4-8.
    assert parsed.commentable_lines == {1, 2, 3, 4, 5, 6, 7, 8}


def test_multiple_hunks_track_their_own_counters():
    diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,3 @@
 line one
+added at two
 line two
@@ -20,2 +21,2 @@
-removed twenty-one
+replaced twenty-one
 context twenty-two
"""
    parsed = parse_unified_diff(diff)[0]
    assert len(parsed.hunks) == 2
    assert sorted(parsed.added_lines) == [2, 21]
    # The second hunk starts at old line 20, so the removed line is 20 (not 21).
    assert 20 in parsed.removed_lines


def test_new_file_and_deleted_file_status():
    diff = """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+import os
+print(os.environ)
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1,1 +0,0 @@
-print("bye")
"""
    files = {f.path: f for f in parse_unified_diff(diff)}
    assert files["new.py"].status == "added"
    assert files["new.py"].added_lines == {1: "import os", 2: "print(os.environ)"}
    assert files["old.py"].status == "removed"
    assert files["old.py"].added_lines == {}


def test_rename_is_detected_from_paths():
    diff = """diff --git a/old_name.py b/new_name.py
--- a/old_name.py
+++ b/new_name.py
@@ -1,1 +1,1 @@
-x = 1
+x = 2
"""
    parsed = parse_unified_diff(diff)[0]
    assert parsed.status == "renamed"
    assert parsed.path == "new_name.py"
    assert parsed.added_lines == {1: "x = 2"}


def test_no_newline_marker_is_ignored():
    diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,1 +1,1 @@
-old
+new
\\ No newline at end of file
"""
    parsed = parse_unified_diff(diff)[0]
    assert parsed.added_lines == {1: "new"}


def test_empty_diff_returns_nothing():
    assert parse_unified_diff("") == []


def test_build_diff_text_round_trips_github_patches():
    text = build_diff_text(
        [
            {
                "path": "app/new.py",
                "old_path": None,
                "patch": "@@ -0,0 +1,2 @@\n+import os\n+print(os.environ)\n",
            }
        ]
    )
    assert text.startswith("diff --git a/app/new.py b/app/new.py")

    parsed = parse_unified_diff(text)
    assert len(parsed) == 1
    assert parsed[0].path == "app/new.py"
    assert parsed[0].added_lines == {1: "import os", 2: "print(os.environ)"}


def test_binary_file_is_marked_and_skipped():
    text = build_diff_text([{"path": "logo.png", "old_path": "logo.png", "patch": None}])
    parsed = parse_unified_diff(text)
    assert parsed[0].is_binary is True
    assert added_lines_by_file(parsed) == {}
    assert commentable_lines_by_file(parsed) == {}


def test_helper_maps_only_files_with_added_lines():
    files = parse_unified_diff(SAMPLE_DIFF)
    mapping = added_lines_by_file(files)
    assert list(mapping) == ["app/services/checkout.py"]
    assert 4 in mapping["app/services/checkout.py"]
