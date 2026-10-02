# ServiceNow Job Agent

Finds ServiceNow ITSM/ITOM jobs (2-5 yrs) posted in the last 3 days and writes `digest.md` (and emails it if configured).

## Setup
1. `pip install -r requirements.txt`
2. Free Adzuna key: https://developer.adzuna.com  ->
   `export ADZUNA_APP_ID=...` and `export ADZUNA_APP_KEY=...`
3. (Optional email via Gmail app password)
   `export EMAIL_USER=you@gmail.com EMAIL_APP_PASSWORD=xxxx EMAIL_TO=you@gmail.com`
4. Add company slugs in `companies.json` (Greenhouse / Lever career pages).
5. Edit `config.json` for location (e.g. `"location_contains": ["bengaluru", "remote"]`), years, keywords.

## Run
`python job_agent.py`

## Run daily
Linux/Mac cron: `0 9 * * * cd /path/job_agent && python3 job_agent.py`
Windows: Task Scheduler. Or GitHub Actions (free) with the keys as secrets.

## Notes
- Greenhouse dates are "last updated", not original posting date.
- Jobs without a stated experience range are kept and shown as "exp: not stated".
- Already-sent jobs are remembered in `seen.json`.
- LinkedIn/Naukri are not scraped. Turn on their job alerts and email forwarding as a separate source.
