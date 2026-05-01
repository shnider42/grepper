from workday_jobs import KeywordRanker, WorkdayClient, WorkdaySiteConfig

config = WorkdaySiteConfig.from_public_url("https://dalcourmaclaren.wd3.myworkdayjobs.com/Dalcour-Maclaren-Careers")

client = WorkdayClient(config)
jobs = client.discover_jobs(max_pages=10, max_jobs=100, hydrate=True)
ranked = KeywordRanker().rank(jobs)

for item in ranked[:25]:
    print(f"{item.score:>6} | {item.job.title} | {item.job.location} | {item.job.url}")
