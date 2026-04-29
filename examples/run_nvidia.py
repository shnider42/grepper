from workday_jobs import KeywordRanker, WorkdayClient, WorkdaySiteConfig

config = WorkdaySiteConfig.from_public_url(
    "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?"
    "locationHierarchy1=2fcb99c455831013ea52fb338f2932d8&"
    "jobFamilyGroup=0c40f6bd1d8f10ae43ffaefd46dc7e78&"
    "jobFamilyGroup=0c40f6bd1d8f10ae43ffbd1459047e84"
)

client = WorkdayClient(config)
jobs = client.discover_jobs(max_pages=10, max_jobs=100, hydrate=True)
ranked = KeywordRanker().rank(jobs)

for item in ranked[:25]:
    print(f"{item.score:>6} | {item.job.title} | {item.job.location} | {item.job.url}")
