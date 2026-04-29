from workday_jobs.parsing import clean_description, extract_json_ld, parse_req_id_from_path


def test_parse_req_id_from_path():
    assert parse_req_id_from_path("/en-US/Site/job/Place/Thing_JR001767") == "JR001767"
    assert parse_req_id_from_path("/en-US/Site/job/Place/Thing_2012720") == "2012720"


def test_clean_description_falls_back_to_full_text():
    html = "<p>This role builds automation.</p><p>Python and Linux required.</p>"
    assert "Python and Linux" in clean_description(html)


def test_clean_description_can_trim_start_and_stop_cues():
    html = "<p>Intro noise</p><p>Job Description Summary: Build systems.</p><p>The US base salary range is...</p>"
    cleaned = clean_description(html)
    assert cleaned.startswith("Build systems")
    assert "salary" not in cleaned.lower()


def test_extract_json_ld():
    html = '<script type="application/ld+json">{"@type":"JobPosting","title":"Engineer"}</script>'
    assert extract_json_ld(html)["title"] == "Engineer"
