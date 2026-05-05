import json

from workday_jobs.icims import IcimsClient, IcimsSiteConfig, extract_icims_job_links, is_icims_url
from workday_jobs.sources import config_from_public_url, provider_name


class FakeResponse:
    def __init__(self, text: str, *, status_code: int = 200, url: str = "") -> None:
        self.text = text
        self.status_code = status_code
        self.url = url
        self.headers = {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.calls = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        for key, value in self.mapping.items():
            if key in url:
                return FakeResponse(value, url=url)
        return FakeResponse("", status_code=404, url=url)


def test_icims_url_detection_and_config_parsing():
    config = IcimsSiteConfig.from_public_url(
        "https://careers-suffolkconstruction.icims.com/jobs/11113/job?utm_source=indeed_integration"
    )

    assert is_icims_url("https://careers-suffolkconstruction.icims.com/jobs/11113/job")
    assert config.base_url == "https://careers-suffolkconstruction.icims.com"
    assert config.company_slug == "suffolkconstruction"
    assert config.job_id == "11113"
    assert config.job_url() == "https://careers-suffolkconstruction.icims.com/jobs/11113/job"


def test_provider_factory_routes_icims_url():
    config = config_from_public_url("https://careers-suffolkconstruction.icims.com/jobs/11113/job")

    assert isinstance(config, IcimsSiteConfig)
    assert provider_name(config) == "iCIMS"


def test_extract_icims_job_links_dedupes_links():
    html = """
    <a href="/jobs/11113/job">Quality Engineer</a>
    <a href="https://careers-suffolkconstruction.icims.com/jobs/22222/job">DevOps Engineer</a>
    <a href="/jobs/11113/job?mode=job">Duplicate</a>
    """

    links = extract_icims_job_links(html, "https://careers-suffolkconstruction.icims.com")

    assert [link["job_id"] for link in links] == ["11113", "22222"]
    assert links[0]["url"] == "https://careers-suffolkconstruction.icims.com/jobs/11113/job"
    assert links[0]["title"] == "Quality Engineer"


def test_direct_job_url_hydrates_from_json_ld():
    json_ld = {
        "@type": "JobPosting",
        "title": "QA Automation Engineer",
        "identifier": {"value": "REQ-11113"},
        "description": "<p>Build Python automation on Linux.</p>",
        "datePosted": "2026-05-01",
        "employmentType": "FULL_TIME",
        "jobLocation": {
            "address": {
                "addressLocality": "Boston",
                "addressRegion": "MA",
                "addressCountry": "US",
            }
        },
        "hiringOrganization": {"name": "Suffolk Construction"},
    }
    html = f'<script type="application/ld+json">{json.dumps(json_ld)}</script>'
    config = IcimsSiteConfig.from_public_url("https://careers-suffolkconstruction.icims.com/jobs/11113/job")
    client = IcimsClient(config, session=FakeSession({"/jobs/11113/job": html}))

    jobs = client.discover_jobs(max_pages=2, max_jobs=1, hydrate=True)

    assert len(jobs) == 1
    assert jobs[0].title == "QA Automation Engineer"
    assert jobs[0].req_id == "REQ-11113"
    assert jobs[0].job_id == "11113"
    assert "Boston" in jobs[0].location
    assert jobs[0].hiring_organization == "Suffolk Construction"
    assert "Python automation" in jobs[0].description_text


def test_search_page_links_can_be_discovered_without_hydration():
    html = '<a href="/jobs/11113/job">Quality Engineer</a><a href="/jobs/22222/job">DevOps Engineer</a>'
    config = IcimsSiteConfig.from_public_url("https://careers-suffolkconstruction.icims.com/jobs/search")
    client = IcimsClient(config, session=FakeSession({"/jobs/search": html}))

    jobs = client.discover_jobs(max_pages=1, max_jobs=10, hydrate=False)

    assert [job.job_id for job in jobs] == ["11113", "22222"]
    assert jobs[0].title == "Quality Engineer"
