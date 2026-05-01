from workday_jobs.config import WorkdaySiteConfig


def test_from_public_url_parses_nvidia_facets():
    config = WorkdaySiteConfig.from_public_url(
        "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?"
        "locationHierarchy1=LOC&jobFamilyGroup=A&jobFamilyGroup=B"
    )
    assert config.base_url == "https://nvidia.wd5.myworkdayjobs.com"
    assert config.tenant == "nvidia"
    assert config.site == "NVIDIAExternalCareerSite"
    assert config.default_facets == {
        "locationHierarchy1": ["LOC"],
        "jobFamilyGroup": ["A", "B"],
    }


def test_from_public_url_parses_locale_site():
    config = WorkdaySiteConfig.from_public_url(
        "https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers/details/Foo_123"
    )
    assert config.tenant == "cisco"
    assert config.site == "Cisco_Careers"
    assert config.locale == "en-US"


def test_from_public_url_parses_myworkdaysite_recruiting_site():
    config = WorkdaySiteConfig.from_public_url(
        "https://wd1.myworkdaysite.com/en-US/recruiting/fmr/FidelityCareers"
    )
    assert config.base_url == "https://wd1.myworkdaysite.com"
    assert config.tenant == "fmr"
    assert config.site == "FidelityCareers"
    assert config.locale == "en-US"
    assert config.public_site_prefix == "/en-US/recruiting/fmr/FidelityCareers"
    assert config.referer == "https://wd1.myworkdaysite.com/en-US/recruiting/fmr/FidelityCareers"
    assert config.list_url == "https://wd1.myworkdaysite.com/wday/cxs/fmr/FidelityCareers/jobs"


def test_from_public_url_parses_netflix_vanity_site():
    config = WorkdaySiteConfig.from_public_url("https://explore.jobs.netflix.net/careers")
    assert config.base_url == "https://netflix.wd1.myworkdayjobs.com"
    assert config.tenant == "netflix"
    assert config.site == "Netflix"
    assert config.list_url == "https://netflix.wd1.myworkdayjobs.com/wday/cxs/netflix/Netflix/jobs"


def test_from_public_url_parses_direct_cxs_endpoint():
    config = WorkdaySiteConfig.from_public_url(
        "https://netflix.wd1.myworkdayjobs.com/wday/cxs/netflix/Netflix/jobs"
    )
    assert config.base_url == "https://netflix.wd1.myworkdayjobs.com"
    assert config.tenant == "netflix"
    assert config.site == "Netflix"
    assert config.list_url == "https://netflix.wd1.myworkdayjobs.com/wday/cxs/netflix/Netflix/jobs"
