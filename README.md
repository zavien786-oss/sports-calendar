# Sports Calendar Aggregator

Builds one `.ics` calendar file with:
- 🏏 Indian national cricket team matches (all formats)
- ⚽ FIFA World Cup matches
- 🎾 Grand Slam tennis matches (Australian Open, French Open, Wimbledon, US Open)

A GitHub Action runs the script every 2 hours and commits the refreshed
`sports.ics` back into this repo, so the file always has up-to-date
schedules and scores.

## 1. Where the data comes from

| Sport   | Source                                  | API key needed?            |
|---------|------------------------------------------|-----------------------------|
| Cricket | [cricapi.com](https://cricapi.com/)       | Yes — **free** tier (100 req/day) |
| Soccer  | ESPN's public site API                    | No                           |
| Tennis  | ESPN's public site API                    | No                           |

ESPN's API is unofficial/undocumented (it's what espn.com itself uses), so
it could change shape someday — if a section ever comes back empty, that's
the first thing to check.

## 2. One-time setup

### a) Get a free cricapi.com key
1. Go to https://cricapi.com/ and click **Sign Up** (free).
2. After verifying your email, copy your **API key** from the dashboard.

### b) Create the GitHub repo
```bash
cd ~/sports-calendar
git init
git add .
git commit -m "Initial sports calendar aggregator"
gh repo create sports-calendar --public --source=. --push
```
(If you don't have the `gh` CLI, create an empty repo on github.com named
`sports-calendar`, then `git remote add origin <url>` and `git push -u origin main`.)

### c) Add your cricapi key as a GitHub secret
In your new repo on GitHub: **Settings → Secrets and variables → Actions →
New repository secret**
- Name: `CRICAPI_KEY`
- Value: *(paste the key from step a)*

### d) Set your timezone (already set to America/New_York)
Match times are converted to whatever `LOCAL_TZ` is set to. It's currently
`America/New_York` in two places — change both if you move:
- `.github/workflows/update-ics.yml` (the `LOCAL_TZ` env var)
- or just always pass `LOCAL_TZ=Some/Timezone` when running locally

### e) Turn the workflow on
The workflow file is already in `.github/workflows/update-ics.yml`. Once
pushed to GitHub, it runs automatically every 2 hours. You can also trigger
it manually anytime: repo → **Actions** tab → **Update sports.ics** →
**Run workflow**.

## 3. Hosting the .ics file (so your phone can subscribe)

The easiest option — **no extra setup, just use the raw file URL**:
```
https://raw.githubusercontent.com/<your-github-username>/sports-calendar/main/sports.ics
```
Every time the Action commits a new `sports.ics`, that URL automatically
serves the latest version.

### Subscribe on iPhone
1. Settings → Calendar → Accounts → **Add Account** → **Other**
2. **Add Subscribed Calendar**
3. Paste the raw URL above → **Next** → **Save**

### Subscribe on Google Calendar (works for Android too)
1. On calendar.google.com, click **+** next to "Other calendars" → **From URL**
2. Paste the raw URL above → **Add calendar**
3. It'll then sync to the Google Calendar app on your Android phone automatically

## 4. Important: this is not truly "live"

Two refresh rates are stacked here, and the slower one wins:
- **Our backend** (the GitHub Action) updates `sports.ics` every 2 hours.
- **Your calendar app** decides on its own how often to re-check a
  subscribed URL — Apple Calendar and Google Calendar typically poll
  every several hours, not every 2 hours, and you can't fully control this.

So treat this as "schedules + score updates a few times a day," not a
ball-by-ball live scoreboard. For real live scores, a live scoring app/site
is still the better tool.

## 5. Known limitations

- **Cricket**: cricapi's free `currentMatches` endpoint only returns
  matches that are live, recently finished, or starting soon — not a full
  season's schedule months in advance.
- **FIFA World Cup**: only populated while a World Cup tournament's date
  window is active (the script reads the tournament's own start/end dates
  from ESPN, so this is automatic).
- **Tennis**: only the 4 Grand Slam windows hardcoded in
  `GRAND_SLAM_WINDOWS` in `aggregate_sports_ics.py` are fetched, and only
  Men's/Women's Singles are included by default (edit
  `TENNIS_GROUPINGS_INCLUDED` in the script to add doubles/mixed).

## 6. Running it locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export CRICAPI_KEY=your_key_here
export LOCAL_TZ=America/New_York
python3 aggregate_sports_ics.py
```
This writes/overwrites `sports.ics` in the current directory.
