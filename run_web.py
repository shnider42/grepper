"""PyCharm-friendly launcher for the local Grepper Workday browser UI.

Run this file from the project root instead of running workday_jobs/web.py directly.
That keeps Python's package context intact, so imports like `from .client import ...`
continue to work correctly inside the workday_jobs package.
"""

from workday_jobs import web


# Local launcher examples layered on top of the browser UI defaults.
# The BorgWarner public page is a branded careers skin backed by Workday.
web.DEFAULT_EXAMPLES.setdefault(
    "BorgWarner",
    "https://www.borgwarner.com/careers/job-search",
)


if __name__ == "__main__":
    raise SystemExit(web.main())
