from workday_jobs import IcimsClient, IcimsSiteConfig, KeywordRanker

config = IcimsSiteConfig.from_public_url("https://careers-suffolkconstruction.icims.com/jobs/search")
client = IcimsClient(config)

jobs = client.discover_jobs(max_pages=3, max_jobs=50, hydrate=True)
ranked = KeywordRanker().rank(jobs)

for item in ranked[:25]:
    print(f"{item.score:>6} | {item.job.title} | {item.job.location} | {item.job.url}")
