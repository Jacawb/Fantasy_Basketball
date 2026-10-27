# Fantasy Basketball AI Manager

A bot that hands full control of an ESPN fantasy basketball team to Google Gemini. Once a day it pulls the team's state from ESPN, asks Gemini what to do, checks that the moves are legal, submits them to ESPN, and posts a summary to Discord.

The prompt describes the league rules only and gives no strategy advice, because the point is to see how Gemini plays on its own.

## How it works

```
state.py  ──►  decide.py  ──►  validate.py  ──►  bot.py  ──►  notify.py
 gather         Gemini          legality         submit        Discord
 ESPN data      decision        checks + retry   to ESPN       log
```

1. **Gather** ([state.py](state.py)): reads the league through `espn-api` and ESPN's scoreboard API. This gives today's roster, the top 40 free agents, who plays today (with tip times in Pacific), recent scoring averages, injuries, the current matchup score, adds used this week, and pending trade offers.
2. **Decide** ([decide.py](decide.py)): sends that state to Gemini with a rules-only system prompt and gets back a structured `Decision`: a slot for every player, an optional add/drop, accept/decline for each trade offer, and a short reasoning.
   - `GEMINI_MODEL` can list several models separated by commas. The first is the primary model and the rest are fallbacks.
   - When a model returns a 503 (overloaded), the bot retries with exponential backoff: about 35 minutes for the primary and about 3 minutes for each fallback. On a 404 or 429, it moves on to the next model.
3. **Validate** ([validate.py](validate.py)): checks legality only (roster size, slot capacity, position eligibility, the 4-center limit, IR rules, OUT players not starting, add limits, and real trade IDs). Moves that are legal but bad still pass. When a decision fails, the error goes back to Gemini, which gets up to 2 retries.
4. **Lineup safety net** ([lineup.py](lineup.py)): if Gemini benches a player who plays today while starting one who doesn't, the bot swaps them in (the only override, since that's never better). If Gemini can't produce a legal decision at all, the bot sets the lineup itself and skips the add/drop and trades for that day instead of skipping the whole day.
5. **Submit** ([bot.py](bot.py)): sends the moves to ESPN's private write API using your session cookies:
   - It runs the add/drop first. When ESPN says the player is on waivers, the bot retries the move as a waiver claim.
   - All lineup changes go out in a single request, so swaps don't collide.
   - It then sends the trade accept/decline responses.
6. **Log** ([notify.py](notify.py)): posts the day's moves, the matchup score, any errors, and Gemini's reasoning to a Discord webhook. When the bot crashes, it posts the traceback there too.

## League assumptions

These rules are hard-coded in the prompt and the validator. Change them in [decide.py](decide.py), [validate.py](validate.py), and [state.py](state.py) if your league differs.

- ESPN, 4 teams, head-to-head points, 19 weekly matchups, every team makes the playoffs
- **Scoring:** PTS +1, REB +1, AST +2, STL +4, BLK +4, 3PM +1, FGM +2, FGA −1, FTM +1, FTA −1, TO −2
- **Roster (13):** PG, SG, SF, PF, C, G, F, UTIL ×3, BE ×3, IR ×1, with at most 4 centers
- At most 7 adds per matchup and 1 add per day, with a 1-day waiver period
- Season year `2027` (set in `state.py`, `bot.py`, `rankings.py`, `push_rankings.py`, and `test.py`)

## Setup

Requires Python 3.12.

```bash
python -m venv venv
```

```bash
venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root (it's already gitignored):

```
LEAGUE_ID=123456
TEAM_ID=1
ESPN_S2=...
SWID={XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
GEMINI_API_KEY=...
GEMINI_MODEL=primary-model,fallback-model
DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
DRY_RUN=true
```

| Variable | What it is |
|---|---|
| `LEAGUE_ID` | The `leagueId` in your ESPN league URL |
| `TEAM_ID` | Your team's ID in that league |
| `ESPN_S2`, `SWID` | ESPN login cookies (copy them from your browser's dev tools while logged in). Keep the braces in `SWID`. |
| `GEMINI_API_KEY` | Google AI Studio API key |
| `GEMINI_MODEL` | One or more Gemini model names, separated by commas. The first is the primary model. |
| `DISCORD_WEBHOOK` | Webhook URL for the channel that receives the daily log |
| `DRY_RUN` | Moves are only submitted to ESPN when this is `false`. **It defaults to `true`.** |

## Usage

Every module can run on its own, which makes testing one stage easy:

```bash
python test.py
```
Checks the ESPN connection by printing your team name and the league settings.

```bash
python state.py
```
Gathers today's state and writes it to `state.json`.

```bash
python decide.py
```
Gets a single Gemini decision without validating it. Nothing is submitted.

```bash
python validate.py
```
Decides and validates, retrying on errors. Nothing is submitted.

```bash
python notify.py
```
Sends a test message to Discord.

```bash
python bot.py
```
Runs the full daily loop. Moves are submitted only when `DRY_RUN=false`.

### Draft rankings (pre-season)

```bash
python rankings.py --check
```
Prints a sample of the player pool so you can confirm the projections loaded.

```bash
python rankings.py
```
Asks Gemini to rank the top 80 players. The results are saved to `rankings.json` and `rankings.txt`.

```bash
python push_rankings.py --send
```
Uploads the ranked list as your ESPN pre-draft list, with unranked players appended in ESPN's default order. Leave off `--send` for a dry run.

## Scheduled runs (GitHub Actions)

[.github/workflows/daily.yml](.github/workflows/daily.yml) runs `bot.py` every day at 15:00 UTC (8 AM PDT / 7 AM PST) with `DRY_RUN=false`. You can also trigger it by hand from the Actions tab.

Add these repository secrets under **Settings → Secrets and variables → Actions**: `LEAGUE_ID`, `TEAM_ID`, `ESPN_S2`, `SWID`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `DISCORD_WEBHOOK`.

## Caveats

- ESPN's write endpoints are undocumented. The payloads copy what ESPN's web app sends. The `TRADE_ACCEPT` transaction type is a guess, because only the decline request was captured.
- `ESPN_S2` and `SWID` expire from time to time. When writes start failing with auth errors, refresh them in `.env` and in the GitHub secrets.
- When a waiver claim is pending, the bot doesn't put the new player in the lineup that day.

## Project layout

| File | Purpose |
|---|---|
| `bot.py` | Daily entry point; ESPN writes and the Discord log format |
| `state.py` | Collects league and roster state |
| `decide.py` | Gemini prompt, response schema, and model fallback |
| `validate.py` | Legality checks and the retry loop |
| `notify.py` | Discord webhook poster |
| `rankings.py` / `push_rankings.py` | Pre-draft rankings from Gemini and upload to ESPN |
| `test.py` | ESPN connection smoke test |
| `rankings.json` / `rankings.txt` | Latest generated draft rankings |
