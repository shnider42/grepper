from workday_jobs import KeywordRanker, WorkdayClient, WorkdaySiteConfig

config = WorkdaySiteConfig.from_public_url(
    "https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers?"
    "jobFamilyGroup=2101eee3ea96016aef42a674fc016429&"
    "jobFamilyGroup=2101eee3ea9601cf53eba574fc016229&"
    "jobFamilyGroup=2101eee3ea96017b1ceba674fc016829"
)

client = WorkdayClient(config)
jobs = client.discover_jobs(max_pages=5, max_jobs=25, hydrate=True)
ranked = KeywordRanker().rank(jobs)

for item in ranked[:25]:
    print(f"{item.score:>6} | {item.job.title} | {item.job.location} | {item.job.url}")
