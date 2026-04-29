from workday_jobs.facets import extract_facet_options, merge_facets, search_facet_options


def test_extract_facet_options_handles_workday_shape():
    payload = {
        "facets": [
            {
                "descriptor": "Location",
                "facetParameter": "locationHierarchy1",
                "values": [
                    {"descriptor": "United States of America", "id": "US_ID", "count": 123},
                    {"descriptor": "Bangalore, India", "id": "BLR_ID", "count": 42},
                ],
            }
        ]
    }

    options = extract_facet_options(payload)

    assert options[0].facet_key == "locationHierarchy1"
    assert options[0].value == "US_ID"
    assert options[0].label == "United States of America"


def test_search_location_supports_us_alias():
    payload = {
        "facets": [
            {
                "descriptor": "Location",
                "facetParameter": "locationHierarchy1",
                "values": [
                    {"descriptor": "United States of America", "id": "US_ID", "count": 123},
                    {"descriptor": "Bangalore, India", "id": "BLR_ID", "count": 42},
                ],
            }
        ]
    }

    matches = search_facet_options(payload, "US", location_only=True)

    assert matches
    assert matches[0].value == "US_ID"


def test_search_location_can_find_city_with_country_suffix():
    payload = {
        "facets": [
            {
                "descriptor": "Locations",
                "facetParameter": "locations",
                "values": [
                    {"descriptor": "Boston, Massachusetts, US", "id": "BOS_ID", "count": 5},
                    {"descriptor": "RTP, North Carolina, US", "id": "RTP_ID", "count": 8},
                ],
            }
        ]
    }

    matches = search_facet_options(payload, "Boston", location_only=True)

    assert matches[0].facet_key == "locations"
    assert matches[0].value == "BOS_ID"


def test_merge_facets_deduplicates_values():
    assert merge_facets({"locations": ["A"]}, {"locations": ["A", "B"]}) == {"locations": ["A", "B"]}
