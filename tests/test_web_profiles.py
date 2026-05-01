from workday_jobs.web import (
    PROFILE_PRESETS,
    SearchForm,
    apply_profile_defaults,
    parse_weight_text,
    profile_from_form,
)


def test_web_profile_presets_include_chris_and_surveying_profiles():
    assert "chris-default" in PROFILE_PRESETS
    assert "surveying-legal-property" in PROFILE_PRESETS
    assert PROFILE_PRESETS["surveying-legal-property"].core_plus["surveying"] == 4.0
    assert PROFILE_PRESETS["surveying-legal-property"].core_plus["zoning"] == 3.5
    assert PROFILE_PRESETS["surveying-legal-property"].light_neg["sales"] == -2.5


def test_apply_profile_defaults_populates_editable_weight_text():
    form = apply_profile_defaults(SearchForm(), "surveying-legal-property")

    assert form.profile_key == "surveying-legal-property"
    assert "surveying = 4" in form.core_plus_weights
    assert "real estate = 1.5" in form.nice_weights
    assert "sales = -2.5" in form.light_neg_weights


def test_profile_from_form_uses_tuned_browser_weights():
    form = SearchForm(
        profile_key="surveying-legal-property",
        core_plus_weights="surveying = 5\nzoning = 3",
        nice_weights="compliance = 2",
        light_neg_weights="sales = -4",
        title_boost=1.5,
        length_bonus_cap=2.0,
        length_bonus_divisor=1000.0,
    )

    profile = profile_from_form(form)

    assert profile.name == "surveying-legal-property"
    assert profile.core_plus == {"surveying": 5.0, "zoning": 3.0}
    assert profile.nice == {"compliance": 2.0}
    assert profile.light_neg == {"sales": -4.0}
    assert profile.title_boost == 1.5
    assert profile.length_bonus_cap == 2.0
    assert profile.length_bonus_divisor == 1000.0


def test_parse_weight_text_rejects_entries_without_weights():
    try:
        parse_weight_text("surveying", "Core weights")
    except ValueError as exc:
        assert "term = weight" in str(exc)
    else:
        raise AssertionError("Expected parse_weight_text to reject missing weight")
