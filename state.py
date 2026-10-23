"""state.py - gather league state for the daily Gemini run."""
import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from espn_api.basketball import League

load_dotenv()
YEAR = 2027
TEAM_ID = int(os.getenv("TEAM_ID"))
PT = ZoneInfo("America/Los_Angeles")
FA_COUNT = 40
ADDS_LIMIT = 7
LOCK_BUFFER = timedelta(minutes=15)  # ESPN locks at scheduled tip; Gemini can take a while
SLOTS = {"PG", "SG", "SF", "PF", "C", "G", "F", "UTIL", "BE", "IR"}
SLOT_FIX = {"UT": "UTIL"}  # espn-api name -> ours

# ESPN site API abbrevs -> espn-api abbrevs
ABBR_FIX = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA",
            "WSH": "WAS", "PHI": "PHL", "PHX": "PHO"}


def get_league():
    return League(league_id=int(os.getenv("LEAGUE_ID")), year=YEAR,
                  espn_s2=os.getenv("ESPN_S2"), swid=os.getenv("SWID"))


def todays_games():
    """NBA teams playing today (Pacific date) -> opponent, tip time, started."""
    now = datetime.now(PT)
    date = now.strftime("%Y%m%d")
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
    events = requests.get(url, params={"dates": date}, timeout=20).json().get("events", [])
    games = {}
    for ev in events:
        comp = ev["competitions"][0]
        tip = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(PT)
        teams = [ABBR_FIX.get(c["team"]["abbreviation"], c["team"]["abbreviation"])
                 for c in comp["competitors"]]
        started = tip <= now + LOCK_BUFFER or ev["status"]["type"]["state"] != "pre"
        for i, t in enumerate(teams):
            games[t] = {"opp": teams[1 - i], "tip_pt": tip.strftime("%I:%M %p").lstrip("0"),
                        "started": started}
    return games


def stat_avg(p, split):
    # split: total, last_7, last_15, last_30
    s = (p.stats or {}).get(f"{YEAR}_{split}") or {}
    val = s.get("applied_avg")
    return round(val, 1) if val is not None else None


def player_info(p, games):
    g = games.get(p.proTeam)
    return {
        "id": p.playerId,
        "name": p.name,
        "team": p.proTeam,
        "pos": p.position,
        "eligible": [SLOT_FIX.get(s, s) for s in p.eligibleSlots if SLOT_FIX.get(s, s) in SLOTS],
        "slot": SLOT_FIX.get(getattr(p, "lineupSlot", None), getattr(p, "lineupSlot", None)),
        "injury": p.injuryStatus,
        "avg": round(p.avg_points or 0, 1),
        "proj_avg": round(getattr(p, "projected_avg_points", 0) or 0, 1),
        "last7": stat_avg(p, "last_7"),
        "last15": stat_avg(p, "last_15"),
        "plays_today": g is not None,
        "locked": bool(g and g["started"]),
        "game": g,
    }


def matchup(league):
    try:
        for m in league.scoreboard():
            ids = (m.home_team.team_id, getattr(m.away_team, "team_id", None))
            if TEAM_ID in ids:
                home = ids[0] == TEAM_ID
                opp = m.away_team if home else m.home_team
                return {
                    "opponent": opp.team_name,
                    "my_score": m.home_final_score if home else m.away_final_score,
                    "opp_score": m.away_final_score if home else m.home_final_score,
                }
    except Exception as e:  # preseason / bye weeks
        return {"error": str(e)}
    return None


def raw(league, views):
    return league.espn_request.league_get(params={"view": views})


def adds_used(data, period):
    team = next(t for t in data.get("teams", []) if t["id"] == TEAM_ID)
    totals = team.get("transactionCounter", {}).get("matchupAcquisitionTotals", {})
    return totals.get(str(period), 0)


def trade_offers(data, league, games):
    """Pending trade offers sent to us, with player info for both sides."""
    players = {p.playerId: p for t in league.teams for p in t.roster}
    teams = {t.team_id: t.team_name for t in league.teams}
    txs = data.get("pendingTransactions") or data.get("transactions") or []
    out = []
    for t in txs:
        if t.get("type") != "TRADE_PROPOSAL" or t.get("status") != "PENDING":
            continue
        # skip our own offers and ones we already answered
        if t.get("teamId") == TEAM_ID or str(TEAM_ID) in (t.get("teamActions") or {}):
            continue
        items = t.get("items", [])

        def side(key):
            out_ = []
            for i in items:
                if i.get(key) == TEAM_ID and i["playerId"] in players:
                    info = player_info(players[i["playerId"]], games)
                    info.pop("slot")  # their slot on the other team, not useful
                    out_.append(info)
            return out_

        out.append({"id": t["id"], "from_team": teams.get(t.get("teamId")),
                    "you_get": side("toTeamId"), "you_give": side("fromTeamId")})
    return out


def gather():
    league = get_league()
    games = todays_games()
    me = next(t for t in league.teams if t.team_id == TEAM_ID)
    period = league.currentMatchupPeriod
    data = raw(league, ["mTeam", "mPendingTransactions"])
    return {
        "date": datetime.now(PT).strftime("%Y-%m-%d"),
        "scoring_period": league.scoringPeriodId,
        "matchup_period": period,
        "adds_used": adds_used(data, period),
        "adds_limit": ADDS_LIMIT,
        "matchup": matchup(league),
        "roster": [player_info(p, games) for p in me.roster],
        "free_agents": [player_info(p, games) for p in league.free_agents(size=FA_COUNT)],
        "pending": trade_offers(data, league, games),
        "teams_playing_today": sorted(games),
    }


if __name__ == "__main__":
    state = gather()
    with open("state.json", "w") as f:
        json.dump(state, f, indent=2, default=str)
    print(f"{state['date']} | period {state['matchup_period']} | "
          f"adds {state['adds_used']}/{state['adds_limit']} | "
          f"roster {len(state['roster'])} | FAs {len(state['free_agents'])} | "
          f"teams today {len(state['teams_playing_today'])}")
