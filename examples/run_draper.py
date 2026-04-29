from workday_jobs import KeywordRanker, WorkdayClient, WorkdaySiteConfig

config = WorkdaySiteConfig(
    base_url="https://draper.wd5.myworkdayjobs.com",
    tenant="draper",
    site="Draper_Careers",
    default_facets={
        "locations": ["137100679bc6100117f740f986e00000"],
        "jobFamilyGroup": ["b9bd15164d241000c3f13e0445530002"],
    },
)

client = WorkdayClient(config)
jobs = client.discover_jobs(max_pages=6, max_jobs=120, hydrate=True)
ranked = KeywordRanker().rank(jobs)

for item in ranked[:25]:
    print(f"{item.score:>6} | {item.job.title} | {item.job.location} | {item.job.url}")
