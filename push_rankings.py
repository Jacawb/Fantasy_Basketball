# Pushes Gemini's rankings (rankings.json) to ESPN pre-draft rankings
import os, json, sys
import requests
from dotenv import load_dotenv
from espn_api.basketball import League

load_dotenv()
LEAGUE_ID = int(os.getenv("LEAGUE_ID"))
TEAM_ID = int(os.getenv("TEAM_ID"))
cookies = {"espn_s2": os.getenv("ESPN_S2"), "SWID": os.getenv("SWID")}

league = League(league_id=LEAGUE_ID, year=2027,
                espn_s2=cookies["espn_s2"], swid=cookies["SWID"])

# name -> ESPN id, in ESPN default order
pool = league.free_agents(size=400)
ids = {p.name: p.playerId for p in pool}

with open("rankings.json") as f:
    ranks = json.load(f)

ordered = []
for r in ranks:
    pid = ids.get(r["name"])
    if pid is None:
        print("No ID found, skipping:", r["name"])
    elif pid not in ordered:
        ordered.append(pid)

# everyone Gemini didn't rank goes after, in ESPN's default order
ordered += [p.playerId for p in pool if p.playerId not in ordered]

print(f"Gemini ranked {len(ranks)}, sending {len(ordered)} total")
for r in ranks[:5]:
    print(r["rank"], r["name"], ids.get(r["name"]))

if "--send" not in sys.argv:
    print("Dry run. Add --send to push to ESPN.")
    sys.exit()

url = (f"https://lm-api-writes.fantasy.espn.com/apis/v3/games/fba/seasons/2027"
       f"/segments/0/leagues/{LEAGUE_ID}/teams/{TEAM_ID}")
body = {"draftStrategy": {"draftList": [{"playerId": i} for i in ordered]}}
r = requests.post(url, json=body, cookies=cookies)
print(r.status_code, r.text[:300])
