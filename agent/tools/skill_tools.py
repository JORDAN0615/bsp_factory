from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


DEFAULT_GENERAL_SKILLS = ["jetson-print-bsp-info", "jetson-build-source"]


def load_known_patterns(skills_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(skills_dir) / "known_error_patterns.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("patterns", []))


def available_skill_folders(skills_dir: str | Path) -> list[str]:
    root = Path(skills_dir)
    if not root.exists():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir())


def build_skill_catalog(skills_dir: str | Path, max_description_chars: int = 1200) -> list[dict[str, str]]:
    catalog: list[dict[str, str]] = []
    for skill_name in available_skill_folders(skills_dir):
        metadata = read_skill_metadata(skills_dir, skill_name, max_description_chars)
        catalog.append(metadata)
    return catalog


def read_skill_metadata(
    skills_dir: str | Path,
    skill_name: str,
    max_description_chars: int = 1200,
) -> dict[str, str]:
    root = Path(skills_dir).resolve()
    folder = (root / skill_name).resolve()
    if root != folder and root not in folder.parents:
        raise ValueError(f"Skill escapes skills dir: {skill_name}")
    if not folder.is_dir():
        raise FileNotFoundError(folder)
    primary = _primary_skill_doc(folder)
    if not primary:
        return {"name": skill_name, "description": "", "domain": ""}
    text = primary.read_text(errors="replace", encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    metadata = yaml.safe_load(frontmatter) if frontmatter else {}
    if not isinstance(metadata, dict):
        metadata = {}
    description = str(metadata.get("description") or _summarize_body(body))
    return {
        "name": str(metadata.get("name") or skill_name),
        "folder": skill_name,
        "description": description[:max_description_chars],
        "domain": str(metadata.get("domain") or ""),
    }


def classify_with_patterns(issue: str, logs: list[str], patterns: list[dict[str, Any]]) -> dict[str, Any]:
    haystack = "\n".join([issue, *logs])
    for pattern in patterns:
        regexes = pattern.get("regex", [])
        hits = [rx for rx in regexes if re.search(rx, haystack, re.IGNORECASE | re.MULTILINE)]
        if hits:
            return {
                "bug_type": pattern.get("bug_type"),
                "error_signatures": hits,
                "suspected_areas": pattern.get("suspected_areas", []),
                "selected_skills": pattern.get("skills", []),
                "confidence": 0.9,
                "reason": f"Matched known pattern: {pattern.get('name')}",
            }
    return {
        "bug_type": "unknown",
        "error_signatures": [],
        "suspected_areas": [],
        "selected_skills": [],
        "confidence": 0.0,
        "reason": "No known error pattern matched.",
    }


def select_skills(
    classification: dict[str, Any],
    skills_dir: str | Path,
    max_skills: int = 3,
) -> list[str]:
    available = set(available_skill_folders(skills_dir))
    selected: list[str] = []
    for skill in classification.get("selected_skills", []):
        if skill in available and skill not in selected:
            selected.append(skill)
        if len(selected) >= max_skills:
            return selected
    if not selected:
        for skill in DEFAULT_GENERAL_SKILLS:
            if skill in available and skill not in selected:
                selected.append(skill)
            if len(selected) >= max_skills:
                break
    return selected


def validate_selected_skills(
    selected_skills: list[str],
    skills_dir: str | Path,
    max_skills: int = 3,
) -> list[str]:
    available = set(available_skill_folders(skills_dir))
    selected: list[str] = []
    for skill in selected_skills:
        if skill in available and skill not in selected:
            selected.append(skill)
        if len(selected) >= max_skills:
            break
    return selected


def read_skill_folder(skills_dir: str | Path, skill_name: str, max_chars: int = 20000) -> str:
    root = Path(skills_dir).resolve()
    folder = (root / skill_name).resolve()
    if root != folder and root not in folder.parents:
        raise ValueError(f"Skill escapes skills dir: {skill_name}")
    if not folder.is_dir():
        raise FileNotFoundError(folder)
    candidates = ["SKILL.md", "README.md", "skill.md", "readme.md"]
    parts = [f"# Skill: {skill_name}\n"]
    for name in candidates:
        path = folder / name
        if path.exists():
            parts.append(path.read_text(errors="replace", encoding="utf-8")[:max_chars])
            return "\n".join(parts)
    md_files = sorted(folder.glob("*.md"))
    if md_files:
        parts.append(md_files[0].read_text(errors="replace", encoding="utf-8")[:max_chars])
    else:
        parts.append("(No primary markdown document found.)")
    return "\n".join(parts)


def load_selected_skills(skills_dir: str | Path, selected_skills: list[str]) -> str:
    docs = []
    for skill in selected_skills:
        docs.append(read_skill_folder(skills_dir, skill))
    return "\n\n---\n\n".join(docs)


def _primary_skill_doc(folder: Path) -> Path | None:
    for name in ["SKILL.md", "README.md", "skill.md", "readme.md"]:
        path = folder / name
        if path.exists():
            return path
    md_files = sorted(folder.glob("*.md"))
    return md_files[0] if md_files else None


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return parts[1].strip(), parts[2].strip()


def _summarize_body(body: str) -> str:
    lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
        if len(" ".join(lines)) > 500:
            break
    return " ".join(lines)
