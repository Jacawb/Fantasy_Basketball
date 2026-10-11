"""decide.py - send league state to Gemini, get back a structured decision."""
import os
import json
from typing import Literal, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL")
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

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
    resp = client.models.generate_content(
        model=MODEL,
        contents=build_prompt(state, error),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=Decision,
        ),
    )
    return resp.parsed  # Decision instance


if __name__ == "__main__":
    # Dry run: no writes to ESPN
    from state import gather
    d = decide(gather())
    print(json.dumps(d.model_dump(), indent=2))
