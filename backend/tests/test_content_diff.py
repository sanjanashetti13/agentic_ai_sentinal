from app.tools.content_diff import (
    extract_goal_match,
    observation_texts_equivalent,
    summarize_text_change,
)


def test_summarize_deadline_change() -> None:
    summary = summarize_text_change(
        "Application deadline: September 14",
        "Application deadline: September 18",
    )
    assert "September 14" in summary
    assert "September 18" in summary


def test_summarize_identical_content() -> None:
    assert (
        summarize_text_change(
            "Application deadline: September 14",
            "Application deadline: September 14",
        )
        == "No meaningful content change."
    )


def test_equivalent_observations_ignore_whitespace_and_clocks() -> None:
    assert observation_texts_equivalent(
        "Application deadline: September 20, 2026  12:01:09",
        "Application deadline: September 20, 2026 12:01:41",
    )
    assert not observation_texts_equivalent(
        "Application deadline: September 20, 2026",
        "Application deadline: December 31, 2026",
    )


def test_quoted_name_is_extracted_without_trailing_quote() -> None:
    match = extract_goal_match(
        "Tell me when the update comes with name 'Sanjana'",
        "Update: Sanjana",
        "Update: sunset",
    )
    assert match.targets == ["Sanjana"]
    assert match.signal == "disappeared"
    assert match.previous_contains["Sanjana"] is True
    assert match.current_contains["Sanjana"] is False

