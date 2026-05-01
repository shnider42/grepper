import json

from workday_jobs.models import JobPosting
from workday_jobs.ranker import KeywordRanker, Profile, load_profile


def _job(title: str, description: str = "") -> JobPosting:
    return JobPosting(
        source="test",
        req_id="1",
        title=title,
        location="",
        posted="",
        url="https://example.com",
        description_text=description,
    )


def test_ranker_prefers_quality_automation_over_unrelated_asic():
    jobs = [
        _job("ASIC Physical Design Engineer", "semiconductor timing constraints"),
        _job("Senior Software Development Engineer in Test", "Python Linux test automation validation"),
    ]

    ranked = KeywordRanker().rank(jobs)

    assert ranked[0].job.title == "Senior Software Development Engineer in Test"
    assert ranked[0].score > ranked[1].score


def test_ranker_understands_customer_facing_phrase_variants():
    jobs = [_job("Solutions Engineer", "customer facing Linux troubleshooting and networking")]

    ranked = KeywordRanker().rank(jobs)

    assert ranked[0].score > 5
    assert any("customer-facing" in hit or "customer facing" in hit for hit in ranked[0].matches["core"])


def test_profile_can_be_loaded_from_json(tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "name": "surveying-legal-property",
                "core_plus": {"surveying": 4, "zoning": 3.5},
                "nice": {"permitting": 1.5},
                "light_neg": {"intern": -2},
            }
        ),
        encoding="utf-8",
    )

    profile = load_profile(profile_path)
    ranked = KeywordRanker(profile).rank(
        [
            _job("Software Engineer", "generic product engineering"),
            _job("Zoning Platform QA Engineer", "surveying permitting workflows"),
        ]
    )

    assert isinstance(profile, Profile)
    assert profile.name == "surveying-legal-property"
    assert ranked[0].job.title == "Zoning Platform QA Engineer"
    assert "profile='surveying-legal-property'" in ranked[0].notes


def test_profile_weight_override_can_add_new_negative_term():
    jobs = [
        _job("Quality Automation Engineer", "python linux"),
        _job("Quality Automation Engineer", "python linux cryptocurrency"),
    ]

    ranked = KeywordRanker().rank(jobs, weights={"cryptocurrency": -5})

    assert ranked[0].job.description_text == "python linux"
    assert ranked[0].score > ranked[1].score
    assert any("cryptocurrency" in hit for hit in ranked[1].matches["neg"])
