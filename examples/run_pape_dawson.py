from workday_jobs import KeywordRanker, WorkdayClient, WorkdaySiteConfig

config = WorkdaySiteConfig.from_public_url("https://papedawson.wd12.myworkdayjobs.com/pde")

client = WorkdayClient(config)
jobs = client.discover_jobs(max_pages=10, max_jobs=100, hydrate=True)
ranked = KeywordRanker().rank(jobs)

for item in ranked[:25]:
    print(f"{item.score:>6} | {item.job.title} | {item.job.location} | {item.job.url}")
