from agent.tools.llm_tools import extract_diff_or_no_patch


def test_extract_diff_from_prose_and_fence() -> None:
    text = """Here is the patch:

```diff
diff --git a/board.dts b/board.dts
--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-old
+new
```
"""

    diff, reason = extract_diff_or_no_patch(text)

    assert reason is None
    assert diff.startswith("diff --git")
    assert "Here is" not in diff


def test_extract_plain_unified_diff_from_fence() -> None:
    text = """```diff
--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-old
+new
```"""

    diff, reason = extract_diff_or_no_patch(text)

    assert reason is None
    assert diff.startswith("--- a/board.dts")
    assert "```" not in diff


def test_extract_concatenates_multiple_fenced_diff_blocks() -> None:
    text = """First file:

```diff
--- a/regulators.dtsi
+++ b/regulators.dtsi
@@ -1 +1 @@
-old-a
+new-a
```

Second file:

```diff
--- a/camera.dtsi
+++ b/camera.dtsi
@@ -1 +1 @@
-old-b
+new-b
```
"""

    diff, reason = extract_diff_or_no_patch(text)

    assert reason is None
    assert "--- a/regulators.dtsi" in diff
    assert "--- a/camera.dtsi" in diff
    assert "Second file" not in diff


def test_extract_diff_from_prose_without_fence() -> None:
    text = """A minimal safe patch is below.

diff --git a/board.dts b/board.dts
--- a/board.dts
+++ b/board.dts
@@ -1 +1 @@
-old
+new
"""

    diff, reason = extract_diff_or_no_patch(text)

    assert reason is None
    assert diff.startswith("diff --git")
    assert "minimal safe" not in diff
