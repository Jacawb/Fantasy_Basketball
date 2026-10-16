"""decide.py - send league state to Gemini, get back a structured decision."""
import os
import json
import time
from typing import Literal, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

load_dotenv()
# Comma-separated: primary first, then fallbacks
MODELS = [m.strip() for m in os.getenv("GEMINI_MODEL").split(",") if m.strip()]
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
last_model = None  # which model made the latest decision

Slot = Literal["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL", "BE", "IR"]


class Assignment(BaseModel):
    player_id: int
    slot: Slot


class TradeResponse(BaseModel):
    transaction_id: str
    action: Literal["accept", "decline"]


class Decision(BaseModel):
    lineup: list[Assignment] = Field(description="Slot for every player on the roster after any add/drop")
    add_player_id: Optional[int] = Field(description="Free agent to add today, or null")
    drop_player_id: Optional[int] = Field(description="Player to drop for the add, or null")
    trade_responses: list[TradeResponse] = Field(description="One entry per pending trade offered to you")
    reasoning: str = Field(description="Short explanation of today's moves")


# Rules only, no strategy coaching - the point is to see how Gemini plays
SYSTEM = """You are the sole manager of a fantasy basketball team in an ESPN league.
You make every decision for the team. Each day you get the full team state and decide today's moves.

LEAGUE: 4 teams, head-to-head points, 19 weekly matchups. All 4 teams make the playoffs (2-week matchups).

SCORING: PTS +1, REB +1, AST +2, STL +4, BLK +4, 3PM +1, FGM +2, FGA -1, FTM +1, FTA -1, TO -2.

ROSTER (13): PG, SG, SF, PF, C, G, F, UTIL, UTIL, UTIL (10 starters), BE x3, IR x1.
- A player may only fill a slot listed in his "eligible".
- Max 4 centers on the roster.
- IR is only for players with injury status OUT.
- Only starters score. Bench (BE) players score nothing.
- No games-played limit.

TRANSACTIONS:
- At most 7 adds per weekly matchup. "adds_used" shows how many are used this matchup.
- At most one add per day. An add requires a drop if the roster is full.
- Waiver period is 1 day. Dropped players go on waivers.
- You may accept or decline trades offered to you. You cannot propose trades.

OUTPUT: assign a slot to every player on the roster (after your add/drop, if any).
Each starting slot holds at most one player; BE holds up to 3, IR up to 1."""


def build_prompt(state, error=None):
    msg = "Today's team state:\n" + json.dumps(state, default=str)
    if error:
        msg += f"\n\nYour previous decision was rejected: {error}\nFix it and decide again."
    return msg


def decide(state, error=None):
    global last_model
    last_err = None
    for idx, model in enumerate(MODELS):
        tries = 7 if idx == 0 else 3  # primary gets ~35 min, fallbacks ~3 min
        for i in range(tries):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=build_prompt(state, error),
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM,
                        response_mime_type="application/json",
                        response_schema=Decision,
                    ),
                )
                last_model = model
                return resp.parsed
            except errors.ServerError as e:  # 503 overload, wait and retry
                last_err = e
                if i < tries - 1:
                    time.sleep(min(60 * 2 ** i, 600))
            except errors.ClientError as e:
                if e.code == 429:  # quota out, retrying won't help
                    last_err = e
                    break
                raise
    raise last_err  # every model failed


if __name__ == "__main__":
    # Dry run: no writes to ESPN
    from state import gather
    d = decide(gather())
    print(f"model: {last_model}")
    print(json.dumps(d.model_dump(), indent=2))
