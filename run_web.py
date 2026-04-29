"""PyCharm-friendly launcher for the local Grepper Workday browser UI.

Run this file from the project root instead of running workday_jobs/web.py directly.
That keeps Python's package context intact, so imports like `from .client import ...`
continue to work correctly inside the workday_jobs package.
"""

from workday_jobs.web import main


if __name__ == "__main__":
    raise SystemExit(main())
