import subprocess
from pathlib import Path

import pytest

from agent.tools.patch_tools import (
    PatchError,
    apply_patch,
    changed_files_from_diff,
    extract_diff_from_patch_md,
    normalize_hunk_headers,
    reverse_patch,
    summarize_diff,
    validate_unified_diff,
)


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)


def test_patch_apply_and_reverse(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "board.dts").write_text('status = "disabled";\n', encoding="utf-8")
    subprocess.run(["git", "add", "board.dts"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    diff = """diff --git a/board.dts b/board.dts
--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-status = "disabled";
+status = "okay";
"""

    validate_unified_diff(diff)
    apply_patch(tmp_path, diff)
    assert (tmp_path / "board.dts").read_text(encoding="utf-8") == 'status = "okay";\n'
    assert changed_files_from_diff(diff) == ["board.dts"]
    assert summarize_diff(diff) == [{"file": "board.dts", "additions": 1, "deletions": 1}]

    reverse_patch(tmp_path, diff)
    assert (tmp_path / "board.dts").read_text(encoding="utf-8") == 'status = "disabled";\n'


def test_extract_diff_from_patch_md_roundtrip() -> None:
    diff = """--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-status = "disabled";
+status = "okay";
"""
    patch_md = (
        "# Patch\n\n"
        "Attempt: `001`\n\n"
        "## Changed Files\n\n"
        "- `board.dts`\n\n"
        "## Diff\n\n"
        "```diff\n"
        f"{diff}"
        "```\n"
    )

    assert extract_diff_from_patch_md(patch_md) == diff


def test_extract_diff_from_patch_md_requires_diff_block() -> None:
    with pytest.raises(PatchError):
        extract_diff_from_patch_md("# Patch\n\nNo diff here.\n")


def test_validate_rejects_new_files() -> None:
    diff = """diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+hello
"""
    with pytest.raises(PatchError):
        validate_unified_diff(diff)


def test_changed_files_from_plain_unified_diff() -> None:
    diff = """--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-old
+new
"""

    assert changed_files_from_diff(diff) == ["board.dts"]
    assert summarize_diff(diff) == [{"file": "board.dts", "additions": 1, "deletions": 1}]


def test_validate_rejects_hunks_without_line_numbers() -> None:
    diff = """--- a/board.dts
+++ b/board.dts
@@
-old
+new
"""
    with pytest.raises(PatchError):
        validate_unified_diff(diff)


def test_normalize_hunk_headers(tmp_path: Path) -> None:
    (tmp_path / "board.dts").write_text("old\nkeep\n", encoding="utf-8")
    diff = """--- a/board.dts
+++ b/board.dts
@@
-old
+new
 keep
"""

    normalized = normalize_hunk_headers(tmp_path, diff)

    assert "@@ -1,2 +1,2 @@" in normalized
    validate_unified_diff(normalized)


def test_normalize_wrong_hunk_counts(tmp_path: Path) -> None:
    (tmp_path / "board.dts").write_text("old\nkeep\n", encoding="utf-8")
    diff = """--- a/board.dts
+++ b/board.dts
@@ -1,5 +1,5 @@
-old
+new
 keep
"""

    normalized = normalize_hunk_headers(tmp_path, diff)

    assert "@@ -1,2 +1,2 @@" in normalized
    validate_unified_diff(normalized)
    assert normalized.endswith("\n")


def test_normalize_whitespace_drift_in_old_block(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "board.dts").write_text(
        "        i2c@0 {\n"
        "            imx219_a@10 {\n"
        '                status = "disabled";\n'
        "            };\n"
        "        };\n",
        encoding="utf-8",
    )
    # LLM drifted: imx219_a@10 line indented 16 spaces instead of 12.
    diff = """--- a/board.dts
+++ b/board.dts
@@
-                imx219_a@10 {
-                status = "disabled";
+                imx219_a@10 {
+                status = "okay";
             };
"""

    normalized = normalize_hunk_headers(tmp_path, diff)

    validate_unified_diff(normalized)
    apply_patch(tmp_path, normalized)
    content = (tmp_path / "board.dts").read_text(encoding="utf-8")
    assert '                status = "okay";\n' in content
    assert "            imx219_a@10 {\n" in content


def test_normalize_whitespace_drift_keeps_new_lines(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "board.dts").write_text(
        "        regulator-a {\n"
        "            enable-active-high;\n"
        "        };\n",
        encoding="utf-8",
    )
    # Context lines drifted by one space; added lines are genuinely new.
    diff = """--- a/board.dts
+++ b/board.dts
@@
        regulator-a {
            enable-active-high;
        };
+
+        regulator-b {
+            enable-active-high;
+        };
"""

    normalized = normalize_hunk_headers(tmp_path, diff)

    validate_unified_diff(normalized)
    apply_patch(tmp_path, normalized)
    content = (tmp_path / "board.dts").read_text(encoding="utf-8")
    assert "        regulator-b {\n" in content


def test_normalize_trims_invented_context_lines(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "board.dts").write_text(
        "/ {\n"
        "    regulators {\n"
        "        regulator-a {\n"
        "            enable-active-high;\n"
        "        };\n"
        "    };\n"
        "};\n",
        encoding="utf-8",
    )
    # The LLM invented a trailing blank context line and a root closing brace
    # that do not exist right after the anchor block in the real file.
    diff = """--- a/board.dts
+++ b/board.dts
@@
         regulator-a {
             enable-active-high;
         };
+
+        regulator-b {
+            enable-active-high;
+        };

 };
"""

    normalized = normalize_hunk_headers(tmp_path, diff)

    validate_unified_diff(normalized)
    apply_patch(tmp_path, normalized)
    content = (tmp_path / "board.dts").read_text(encoding="utf-8")
    assert "        regulator-b {\n" in content


def test_normalize_single_line_hunk_pads_context(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "board.dts").write_text("a\nold\nc\n", encoding="utf-8")
    diff = """--- a/board.dts
+++ b/board.dts
@@
-old
+new
"""

    normalized = normalize_hunk_headers(tmp_path, diff)

    # Context is padded from the file so git apply accepts the hunk.
    assert "@@ -1,3 +1,3 @@" in normalized
    assert " a\n-old\n+new\n c\n" in normalized
    validate_unified_diff(normalized)
    apply_patch(tmp_path, normalized)
    assert (tmp_path / "board.dts").read_text(encoding="utf-8") == "a\nnew\nc\n"
