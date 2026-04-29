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
