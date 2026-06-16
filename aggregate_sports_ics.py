#!/usr/bin/env python3
"""
Aggregates schedules + live scores for:
  - Indian national cricket team (all formats)        -> cricapi.com (free key, currentMatches)
  - FIFA World Cup                                     -> ESPN's public site API (no key)
  - Tennis Grand Slams (AO, French Open, Wimbledon, US Open) -> ESPN's public site API (no key)

and writes them all into a single sports.ics file.

Run every 2 hours (see .github/workflows/update-ics.yml) to keep scores fresh.
"""
import os
import sys
import json
import datetime as dt
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar, Event

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LOCAL_TZ = ZoneInfo(os.environ.get("LOCAL_TZ", "America/New_York"))
CRICAPI_KEY = os.environ.get("CRICAPI_KEY", "")
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "sports.ics")
HTTP_TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0 (sports-calendar-aggregator)"}
UTC = dt.timezone.utc

# Approximate Grand Slam windows (month, day) -> used to ask ESPN for the
# right date range. Adjust if a slam's dates shift in a given year.
YEAR = dt.datetime.now(UTC).year
GRAND_SLAM_WINDOWS = {
    "Australian Open": ((YEAR, 1, 8), (YEAR, 1, 28)),
    "French Open": ((YEAR, 5, 19), (YEAR, 6, 9)),
    "Wimbledon": ((YEAR, 6, 29), (YEAR, 7, 14)),
    "US Open": ((YEAR, 8, 18), (YEAR, 9, 8)),
}

# ESPN returns the *entire* slam (both tours, all draws) from a single tour's
# scoreboard endpoint, so we only need to query one tour ("atp") to get
# everything - querying "wta" too would just duplicate every match.
# Limit which draws end up on the calendar here (add "Men's Doubles",
# "Women's Doubles", "Mixed Doubles" if you want those too).
TENNIS_GROUPINGS_INCLUDED = {"Men's Singles", "Women's Singles"}


def log(msg):
    print(msg, file=sys.stderr)


def safe_get(url, params=None):
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        log(f"[warn] request failed for {url} ({params}): {exc}")
        return None


def to_local(dt_str_or_utc):
    """Accepts a UTC datetime and returns it converted to LOCAL_TZ."""
    return dt_str_or_utc.astimezone(LOCAL_TZ)


def make_event(uid, summary, start_utc, duration_hours, description, location=""):
    event = Event()
    event.add("uid", uid)
    event.add("summary", summary)
    event.add("dtstart", to_local(start_utc))
    event.add("dtend", to_local(start_utc + dt.timedelta(hours=duration_hours)))
    event.add("dtstamp", dt.datetime.now(UTC))
    event.add("description", description)
    if location:
        event.add("location", location)
    return event


# ---------------------------------------------------------------------------
# Cricket - Indian national team, all formats (cricapi.com, free tier key)
# ---------------------------------------------------------------------------
def fetch_cricket_events():
    events = []
    if not CRICAPI_KEY:
        log("[warn] CRICAPI_KEY not set - skipping cricket section. "
            "Get a free key at https://cricapi.com/ and set it as an env var / GitHub secret.")
        return events

    data = safe_get(
        "https://api.cricapi.com/v1/currentMatches",
        params={"apikey": CRICAPI_KEY, "offset": 0},
    )
    if not data or data.get("status") != "success":
        log(f"[warn] cricapi.com did not return success: {data}")
        return events

    for match in data.get("data", []):
        teams = match.get("teams") or []
        if not any("india" in t.lower() for t in teams):
            continue

        date_str = match.get("dateTimeGMT")
        if not date_str:
            continue
        try:
            start_utc = dt.datetime.fromisoformat(date_str.replace(" ", "T")).replace(tzinfo=UTC)
        except ValueError:
            continue

        match_type = (match.get("matchType") or "").upper()
        name = match.get("name", " vs ".join(teams))
        status = match.get("status", "Scheduled")

        score_lines = []
        for innings in match.get("score", []) or []:
            score_lines.append(
                f"{innings.get('inning', '')}: {innings.get('r', '?')}/{innings.get('w', '?')} "
                f"({innings.get('o', '?')} ov)"
            )
        description = status if not score_lines else status + "\n" + "\n".join(score_lines)

        # Test matches run ~8h/day across up to 5 days; limited overs are shorter.
        duration = {"test": 8, "odi": 8, "t20": 4}.get(match.get("matchType", "").lower(), 4)

        events.append(
            make_event(
                uid=f"cricket-{match.get('id')}@sports-calendar",
                summary=f"🏏 {name} ({match_type})",
                start_utc=start_utc,
                duration_hours=duration,
                description=description,
                location=match.get("venue", ""),
            )
        )
    log(f"[info] cricket: {len(events)} India matches found")
    return events


# ---------------------------------------------------------------------------
# FIFA World Cup (ESPN public site API, no key)
# ---------------------------------------------------------------------------
def fetch_fifa_events():
    events = []
    meta = safe_get("https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard")
    if not meta or not meta.get("leagues"):
        log("[warn] could not load FIFA World Cup league metadata")
        return events

    league = meta["leagues"][0]
    start = league.get("calendarStartDate", "")[:10].replace("-", "")
    end = league.get("calendarEndDate", "")[:10].replace("-", "")
    data = safe_get(
        "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard",
        params={"dates": f"{start}-{end}"} if start and end else None,
    )
    if not data:
        return events

    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        try:
            start_utc = dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue

        competitors = comp.get("competitors", [])
        names, score_bits = [], []
        for c in competitors:
            team_name = c.get("team", {}).get("displayName", "?")
            names.append(team_name)
            score_bits.append(f"{team_name} {c.get('score', '-')}")
        title = " vs ".join(names) if names else ev.get("name", "Match")

        status = comp.get("status", {}).get("type", {}).get("detail", "Scheduled")
        description = f"{' - '.join(score_bits)}\n{status}" if score_bits else status
        venue = comp.get("venue", {}).get("fullName", "")

        events.append(
            make_event(
                uid=f"fifa-{ev.get('id')}@sports-calendar",
                summary=f"⚽ {title} (FIFA World Cup)",
                start_utc=start_utc,
                duration_hours=2,
                description=description,
                location=venue,
            )
        )
    log(f"[info] fifa world cup: {len(events)} matches found")
    return events


# ---------------------------------------------------------------------------
# Tennis Grand Slams (ESPN public site API, no key)
# ---------------------------------------------------------------------------
def fetch_tennis_events():
    events = []
    for slam_name, ((y1, m1, d1), (y2, m2, d2)) in GRAND_SLAM_WINDOWS.items():
        date_range = f"{y1:04d}{m1:02d}{d1:02d}-{y2:04d}{m2:02d}{d2:02d}"
        data = safe_get(
            "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
            params={"dates": date_range},
        )
        if not data:
            continue

        for ev in data.get("events", []):
            if not ev.get("major") or slam_name.lower() not in ev.get("name", "").lower():
                continue
            for grouping in ev.get("groupings", []):
                g_name = grouping.get("grouping", {}).get("displayName", "")
                if g_name not in TENNIS_GROUPINGS_INCLUDED:
                    continue
                for comp in grouping.get("competitions", []):
                        try:
                            start_utc = dt.datetime.fromisoformat(
                                comp["date"].replace("Z", "+00:00")
                            )
                        except (KeyError, ValueError):
                            continue

                        competitors = comp.get("competitors", [])
                        names = [
                            c.get("athlete", {}).get("displayName", "?") for c in competitors
                        ]
                        title = " vs ".join(names) if names else "Match"

                        status = comp.get("status", {}).get("type", {}).get("detail", "Scheduled")
                        score_bits = []
                        for c in competitors:
                            athlete = c.get("athlete", {}).get("displayName", "?")
                            sets = ", ".join(
                                str(ls.get("value")) for ls in c.get("linescores", [])
                            )
                            score_bits.append(f"{athlete}: {sets}" if sets else athlete)
                        description = f"{status}\n" + "\n".join(score_bits)
                        venue = comp.get("venue", {}).get("fullName", "")

                        events.append(
                            make_event(
                                uid=f"tennis-{comp.get('id')}@sports-calendar",
                                summary=f"🎾 {title} ({slam_name}, {g_name})",
                                start_utc=start_utc,
                                duration_hours=3,
                                description=description,
                                location=venue,
                            )
                        )
    log(f"[info] tennis grand slams: {len(events)} matches found")
    return events


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    cal = Calendar()
    cal.add("prodid", "-//sports-calendar-aggregator//github.com//")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "🏏 Cricket (India) / ⚽ FIFA World Cup / 🎾 Grand Slams")
    cal.add("x-wr-timezone", str(LOCAL_TZ))

    all_events = fetch_cricket_events() + fetch_fifa_events() + fetch_tennis_events()
    for event in all_events:
        cal.add_component(event)

    tmp_path = OUTPUT_PATH + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(cal.to_ical())
    os.replace(tmp_path, OUTPUT_PATH)
    log(f"[info] wrote {len(all_events)} total events to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
