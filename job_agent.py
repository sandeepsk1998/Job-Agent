#!/usr/bin/env python3
"""
ServiceNow Job Agent
Collects ServiceNow ITSM/ITOM jobs (2-5 yrs) posted in the last N days from:
  - Greenhouse company boards (public API)
  - Lever company boards (public API)
  - Adzuna job API (free key, covers India)
Sends a digest by email (optional) and always writes digest.md.

Run:  python job_agent.py
"""
import os, re, json, csv, html, smtplib, sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
COMPANIES = json.load(open(os.path.join(BASE, "companies.json"), encoding="utf-8"))
SEEN_FILE = os.path.join(BASE, "seen.json")
HEADERS = {"User-Agent": "personal-job-agent/1.0"}
NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(days=CFG["days"])


# ---------- helpers ----------
def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or ""))).strip()

def parse_dt(s):
    if not s:
        return None
    try:
        if isinstance(s, (int, float)):
            return datetime.fromtimestamp(s / 1000, tz=timezone.utc)
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def job(title, company, location, url, posted, text, source):
    return dict(title=title or "", company=company or "", location=location or "",
                url=url or "", posted=posted, text=strip_html(text), source=source)

def get_json(url, **params):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=25)
        if r.status_code == 200:
            return r.json()
        print(f"  ! {r.status_code} for {url}")
    except Exception as e:
        print(f"  ! error {url}: {e}")
    return None


# ---------- sources ----------
def from_greenhouse(board):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", content="true")
    out = []
    for j in (data or {}).get("jobs", []):
        out.append(job(j.get("title"), board, (j.get("location") or {}).get("name"),
                       j.get("absolute_url"), parse_dt(j.get("updated_at")),
                       j.get("content"), "Greenhouse"))
    return out

def from_lever(company):
    data = get_json(f"https://api.lever.co/v0/postings/{company}", mode="json")
    out = []
    for j in data or []:
        out.append(job(j.get("text"), company, (j.get("categories") or {}).get("location"),
                       j.get("hostedUrl"), parse_dt(j.get("createdAt")),
                       j.get("descriptionPlain") or j.get("description"), "Lever"))
    return out

def from_adzuna():
    app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        print("Adzuna skipped (set ADZUNA_APP_ID and ADZUNA_APP_KEY)")
        return []
    out = []
    for q in CFG["adzuna_queries"]:
        for page in (1, 2, 3):
            data = get_json(f"https://api.adzuna.com/v1/api/jobs/{CFG['adzuna_country']}/search/{page}",
                            app_id=app_id, app_key=app_key, what=q, where=CFG.get("location", ""),
                            max_days_old=CFG["days"], results_per_page=50, sort_by="date")
            for j in (data or {}).get("results", []):
                out.append(job(j.get("title"), (j.get("company") or {}).get("display_name"),
                               (j.get("location") or {}).get("display_name"),
                               j.get("redirect_url"), parse_dt(j.get("created")),
                               j.get("description"), "Adzuna"))
    return out


# ---------- filters ----------
def experience_range(text):
    """Return (lo, hi) years found near the word 'experience', else None."""
    pats = [
        (r"(\d{1,2})\s*\+?\s*(?:-|\u2013|to)\s*(\d{1,2})\s*\+?\s*(?:years|yrs|year)", "range"),
        (r"(\d{1,2})\s*\+?\s*(?:years|yrs|year)", "single"),
    ]
    low = text.lower()
    for pat, kind in pats:
        for m in re.finditer(pat, low):
            ctx = low[max(0, m.start() - 70): m.end() + 70]
            if "experience" not in ctx and "exp" not in ctx:
                continue
            if kind == "range":
                return int(m.group(1)), int(m.group(2))
            return int(m.group(1)), 99
    return None

def relevant(j):
    blob = f"{j['title']} {j['text']}".lower()
    if not any(k in blob for k in CFG["must_have_any"]):
        return False
    if not any(k in blob for k in CFG["module_keywords"]):
        return False
    if any(k in j["title"].lower() for k in CFG["exclude_title_words"]):
        return False
    if CFG.get("location_contains"):
        loc = f"{j['location']} {j['title']}".lower()
        if not any(l in loc for l in CFG["location_contains"]):
            return False
    exp = experience_range(j["text"])
    j["exp"] = f"{exp[0]}-{exp[1]} yrs" if exp and exp[1] != 99 else (f"{exp[0]}+ yrs" if exp else "not stated")
    if exp and not (exp[0] <= CFG["max_years"] and exp[1] >= CFG["min_years"]):
        return False
    return True

def recent(j):
    return j["posted"] is None or j["posted"] >= CUTOFF

def dedupe(jobs):
    seen, out = set(), []
    for j in jobs:
        key = re.sub(r"\W+", "", f"{j['title']}{j['company']}{j['location']}".lower())
        if key in seen or j["url"] in seen:
            continue
        seen.add(key); seen.add(j["url"]); out.append(j)
    return out


# ---------- output ----------
def build_digest(jobs):
    lines = [f"# ServiceNow jobs - last {CFG['days']} days ({NOW:%d %b %Y})", f"{len(jobs)} new matches\n"]
    for j in jobs:
        d = j["posted"].strftime("%d %b") if j["posted"] else "date n/a"
        lines.append(f"**{j['title']}** - {j['company']} ({j['location'] or 'location n/a'})\n"
                     f"{d} | exp: {j['exp']} | {j['source']}\n{j['url']}\n")
    return "\n".join(lines)

def save_csv(jobs):
    """Append every new job to jobs.csv (cumulative list of all jobs found)."""
    path = os.path.join(BASE, "jobs.csv")
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["Found on", "Posted", "Title", "Company", "Location", "Experience", "Source", "Link"])
        for j in jobs:
            w.writerow([NOW.strftime("%Y-%m-%d"), j["posted"].strftime("%Y-%m-%d") if j["posted"] else "",
                        j["title"], j["company"], j["location"], j["exp"], j["source"], j["url"]])

def send_email(body):
    user, pw, to = os.getenv("EMAIL_USER"), os.getenv("EMAIL_APP_PASSWORD"), os.getenv("EMAIL_TO")
    if not (user and pw and to):
        print("Email skipped (set EMAIL_USER, EMAIL_APP_PASSWORD, EMAIL_TO)")
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = "ServiceNow job digest", user, to
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw); s.send_message(msg)
    print("Email sent.")


def main():
    jobs = []
    for b in COMPANIES.get("greenhouse", []):
        print("Greenhouse:", b); jobs += from_greenhouse(b)
    for c in COMPANIES.get("lever", []):
        print("Lever:", c); jobs += from_lever(c)
    print("Adzuna..."); jobs += from_adzuna()
    print(f"Fetched {len(jobs)} jobs")

    jobs = [j for j in jobs if recent(j) and relevant(j)]
    jobs = dedupe(jobs)
    seen = set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()
    new = [j for j in jobs if j["url"] not in seen]
    new.sort(key=lambda j: j["posted"] or NOW, reverse=True)

    if not new:
        print("No new matching jobs."); return
    digest = build_digest(new)
    open(os.path.join(BASE, "digest.md"), "w", encoding="utf-8").write(digest)
    print(digest)
    save_csv(new)
    send_email(digest)
    json.dump(sorted(seen | {j["url"] for j in new}), open(SEEN_FILE, "w"))

if __name__ == "__main__":
    main()
