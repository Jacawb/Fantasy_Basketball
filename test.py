import os
from dotenv import load_dotenv
from espn_api.basketball import League

load_dotenv()
league = League(league_id=int(os.getenv("LEAGUE_ID")), year=2027,
                espn_s2=os.getenv("ESPN_S2"), swid=os.getenv("SWID"))
team = next(t for t in league.teams if t.team_id == int(os.getenv("TEAM_ID")))
print(team.team_name)
print(vars(league.settings))