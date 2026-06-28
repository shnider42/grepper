# Keyword profiles

Reusable ranking profiles live here as JSON files. They can be passed to the CLI with `--profile`.

Example:

```bash
workday-jobs \
  --url "https://company.wd5.myworkdayjobs.com/Company_Careers" \
  --profile profiles/interdisciplinary_embedded_systems.json \
  --pages 5 \
  --max-jobs 75
```

## Profile format

Each profile follows the `workday_jobs.ranker.Profile` schema:

- `name`: profile identifier.
- `core_plus`: strong positive keywords and weights.
- `nice`: softer positive keywords and weights.
- `light_neg`: negative or deprioritizing keywords and weights.
- `title_boost`: multiplier applied when a term appears in the job title.
- `length_bonus_cap`: maximum score bonus for richer job descriptions.
- `length_bonus_divisor`: controls how quickly the description-length bonus accrues.

## `interdisciplinary_embedded_systems.json`

Built from a resume/background centered on senior/principal software engineering, embedded systems, control systems, robotics, grid-scale energy storage, secure OS/TEE work, full-stack connected-device applications, and cross-functional hardware/software requirements capture.
