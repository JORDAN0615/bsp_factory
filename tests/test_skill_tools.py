from agent.tools.skill_tools import (
    build_skill_catalog,
    classify_with_patterns,
    load_known_patterns,
    select_skills,
    validate_selected_skills,
)


def test_known_error_patterns_match_camera() -> None:
    patterns = load_known_patterns("skills")
    result = classify_with_patterns(
        "camera probe failed",
        ["imx219 probe failed with i2c -121"],
        patterns,
    )

    assert result["bug_type"] == "camera_probe_failure"
    assert "camera" in result["suspected_areas"]


def test_select_skills_limits_to_available_folders() -> None:
    classification = {
        "selected_skills": [
            "jetson-customize-camera",
            "missing-skill",
            "jetson-customize-pinmux",
            "jetson-print-bsp-info",
            "jetson-build-source",
        ]
    }

    selected = select_skills(classification, "skills", max_skills=3)

    assert selected == [
        "jetson-customize-camera",
        "jetson-customize-pinmux",
        "jetson-print-bsp-info",
    ]


def test_build_skill_catalog_reads_metadata_without_full_skill_body() -> None:
    catalog = build_skill_catalog("skills")
    camera = next(item for item in catalog if item["folder"] == "jetson-customize-camera")

    assert camera["folder"] == "jetson-customize-camera"
    assert "camera" in camera["description"].lower()
    assert "mipi" in camera["description"].lower()


def test_validate_selected_skills_filters_unknown_and_limits() -> None:
    selected = validate_selected_skills(
        [
            "jetson-customize-camera",
            "missing",
            "jetson-customize-pinmux",
            "jetson-print-bsp-info",
        ],
        "skills",
        max_skills=2,
    )

    assert selected == ["jetson-customize-camera", "jetson-customize-pinmux"]
