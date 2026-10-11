# Builds draft rankings with Gemini from ESPN player projections
import os, json, sys
from dotenv import load_dotenv
from espn_api.basketball import League
from google import genai
from pydantic import BaseModel

load_dotenv()
league = League(league_id=int(os.getenv("LEAGUE_ID")), year=2027,
                espn_s2=os.getenv("ESPN_S2"), swid=os.getenv("SWID"))

SCORING = "PTS +1, REB +1, AST +2, STL +4, BLK +4, 3PM +1, FGM +2, FGA -1, FTM +1, FTA -1, TO -2"
ROSTER = "13 players: starters PG, SG, SF, PF, C, G, F, UTIL x3 (10 total), bench x3, plus 1 IR slot. Max 4 C. No games-played limit."
TOP_N = 80  # make this >= 4 x roster size

# pre-draft, free agents = the whole player pool
pool = []
for p in league.free_agents(size=250):
    pool.append({
        "name": p.name,
        "pos": p.position,
        "slots": getattr(p, "eligibleSlots", None),
        "team": p.proTeam,
        "injury": p.injuryStatus,
        "proj_avg": getattr(p, "projected_avg_points", None),
        "proj_total": getattr(p, "projected_total_points", None),
    })

# sanity check: projections should be real numbers, not None/0
print(json.dumps(pool[:3], indent=2))
if "--check" in sys.argv:
    sys.exit()

class Pick(BaseModel):
    rank: int
    name: str
    reason: str

class Rankings(BaseModel):
    rankings: list[Pick]

prompt = f"""You are managing a fantasy basketball team. Build your draft rankings.

League: ESPN, 4 teams, head-to-head points, weekly matchups. All 4 teams make the playoffs
(regular season only sets seeding; playoff matchups are 2 weeks). Up to 7 pickups per weekly matchup (about 1 per day). Lineups set daily, each player locks at his game time.
Scoring: {SCORING}
Roster slots: {ROSTER}

Your team will autodraft straight down your list, so order matters and positions must
fill the roster legally. Rank your top {TOP_N} players. Use only players from this pool:
{json.dumps(pool)}
"""

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
resp = client.models.generate_content(
    model=os.getenv("GEMINI_MODEL"),
    contents=prompt,
    config={"response_mime_type": "application/json", "response_schema": Rankings},
)

ranks = resp.parsed.rankings
names = {p["name"] for p in pool}
bad = [r.name for r in ranks if r.name not in names]
if bad:
    print("Not in pool (check spelling):", bad)

with open("rankings.json", "w") as f:
    json.dump([r.model_dump() for r in ranks], f, indent=2)
with open("rankings.txt", "w") as f:
    for r in ranks:
        f.write(f"{r.rank}. {r.name} - {r.reason}\n")
print(f"Saved {len(ranks)} players to rankings.txt")
