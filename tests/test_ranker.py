from workday_jobs.models import JobPosting
from workday_jobs.ranker import KeywordRanker


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
