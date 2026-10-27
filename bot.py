"""bot.py - daily loop: gather -> decide -> validate -> submit -> log."""
import os
import traceback

import requests

import decide as dmod
from notify import post
from lineup import autostart, solve
from state import gather
from validate import decide_valid, validate

DRY_RUN = os.getenv("DRY_RUN", "true").lower() != "false"

TEAM_ID = int(os.getenv("TEAM_ID"))
WRITE_URL = ("https://lm-api-writes.fantasy.espn.com/apis/v3/games/fba/seasons/2027"
             f"/segments/0/leagues/{os.getenv('LEAGUE_ID')}/transactions/")
SLOT_IDS = {"PG": 0, "SG": 1, "SF": 2, "PF": 3, "C": 4, "G": 5, "F": 6,
            "UTIL": 11, "BE": 12, "IR": 13}


class EspnError(Exception):
    pass


# --- ESPN writes ---
def post_txn(state, type_, **extra):
    """POST one transaction like the web app does. Returns ESPN's response."""
    payload = {"isLeagueManager": False, "teamId": TEAM_ID, "type": type_,
               "memberId": os.getenv("SWID"),  # SWID incl. braces
               "scoringPeriodId": state["scoring_period"],
               "executionType": "EXECUTE", **extra}
    r = requests.post(WRITE_URL, json=payload, timeout=30,
                      cookies={"espn_s2": os.getenv("ESPN_S2"), "SWID": os.getenv("SWID")},
                      headers={"X-Fantasy-Platform": "espn-fantasy-web",
                               "X-Fantasy-Source": "kona"})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if not r.ok:
        msgs = body.get("messages") or [r.text[:300]]
        codes = [x.get("type") for x in body.get("details", [])]
        raise EspnError(f"{type_} {r.status_code}: {'; '.join(msgs)} {codes}")
    if body.get("status") not in ("EXECUTED", "PENDING"):
        raise EspnError(f"{type_} unexpected status {body.get('status')}")
    return body


def submit_add_drop(add_id, drop_id, state):
    """Returns 'EXECUTED', or 'PENDING' for a waiver claim."""
    items = []
    if add_id:
        items.append({"playerId": add_id, "type": "ADD", "toTeamId": TEAM_ID})
    if drop_id:
        items.append({"playerId": drop_id, "type": "DROP", "fromTeamId": TEAM_ID})
    try:
        return post_txn(state, "FREEAGENT", items=items)["status"]
    except EspnError as e:
        # espn-api doesn't flag waiver players, so retry as a claim if ESPN says so
        if not add_id or "WAIVER" not in str(e).upper():
            raise
        return post_txn(state, "WAIVER", items=items, bidAmount=None)["status"]


def submit_lineup(changes, state):
    # all moves in one request so swaps don't collide
    items = [{"playerId": pid, "type": "LINEUP",
              "fromLineupSlotId": SLOT_IDS[old], "toLineupSlotId": SLOT_IDS[new]}
             for pid, old, new in changes]
    post_txn(state, "ROSTER", items=items)


def submit_trade(tx_id, action, state):
    # TRADE_ACCEPT is a guess (only decline was captured)
    type_ = "TRADE_ACCEPT" if action.lower() == "accept" else "TRADE_DECLINE"
    post_txn(state, type_, comment="", relatedTransactionId=tx_id)


# --- helpers ---
def lineup_changes(d, state):
    """Only the moves that differ from the current lineup."""
    current = {p["id"]: p["slot"] for p in state["roster"]}
    # new adds land on the bench
    return [(a.player_id, current.get(a.player_id, "BE"), a.slot)
            for a in d.lineup if current.get(a.player_id, "BE") != a.slot]


def auto_decision(lineup, reason):
    return dmod.Decision(lineup=[dmod.Assignment(player_id=pid, slot=s) for pid, s in lineup.items()],
                         add_player_id=None, drop_player_id=None, trade_responses=[],
                         reasoning=f"Auto lineup (Gemini failed): {reason[:300]}")


def format_log(d, state, changes, errors=(), claim_pending=False, notes=()):
    names = {p["id"]: p["name"] for p in state["roster"] + state["free_agents"]}
    n = lambda pid: names.get(pid, pid)
    offers = {t["id"]: t for t in state["pending"]}
    m = state.get("matchup") or {}
    lines = [f"**{state['date']}** | matchup {state['matchup_period']} | "
             f"adds {state['adds_used']}/{state['adds_limit']}"]
    if "my_score" in m:
        lines.append(f"vs {m['opponent']}: {m['my_score']} - {m['opp_score']}")
    header_len = len(lines)
    if d.add_player_id:
        lines.append(f"➕ Add {n(d.add_player_id)}")
    if d.drop_player_id:
        lines.append(f"➖ Drop {n(d.drop_player_id)}")
    for pid, old, new in changes:
        lines.append(f"🔁 {n(pid)}: {old} → {new}")
    for t in d.trade_responses:
        o = offers.get(t.transaction_id, {})
        get = ", ".join(p["name"] for p in o.get("you_get", []))
        give = ", ".join(p["name"] for p in o.get("you_give", []))
        lines.append(f"🤝 {t.action} trade from {o.get('from_team', '?')}: get {get} for {give}")
    if len(lines) == header_len:
        lines.append("No moves today")
    if claim_pending and not errors:
        lines.append("⏳ Waiver claim pending, lineup for new player skipped")
    lines.extend(notes)
    for e in errors:
        lines.append(f"❌ {e}")
    if dmod.last_model and dmod.last_model != dmod.MODELS[0]:
        lines.append(f"⚠️ Fallback model used: {dmod.last_model}")
    lines.append(f"\n> {d.reasoning}")
    if DRY_RUN:
        lines.insert(0, "🧪 DRY RUN (nothing submitted)")
    return "\n".join(lines)


def run():
    state = gather()
    notes = []
    try:
        d, err = decide_valid(state)
    except Exception as e:  # every Gemini model failed
        d, err = None, f"Gemini failed: {e}"
    if d is None:
        # Never skip the day: keep the roster, set the lineup ourselves
        auto = solve(state)
        if auto is None or validate(d := auto_decision(auto, err), state):
            post(f"⚠️ {state['date']}: skipped day, invalid after retries:\n{err}")
            return
        notes.append("🛟 Gemini had no legal lineup; auto lineup used, no add/drop or trades today")
    else:
        lineup, gained = autostart({a.player_id: a.slot for a in d.lineup}, state,
                                   d.add_player_id, d.drop_player_id)
        fixed = d.model_copy(update={"lineup": [dmod.Assignment(player_id=pid, slot=s)
                                                for pid, s in lineup.items()]})
        if gained and validate(fixed, state) is None:
            d = fixed
            names = {p["id"]: p["name"] for p in state["roster"] + state["free_agents"]}
            notes.append("🛟 Auto-started (playing today, were benched): "
                         + ", ".join(names.get(pid, str(pid)) for pid in gained))

    changes = lineup_changes(d, state)
    errors, claim_pending = [], False
    if not DRY_RUN:
        # Add/drop first so the lineup can use the new player
        if d.add_player_id or d.drop_player_id:
            try:
                claim_pending = submit_add_drop(d.add_player_id, d.drop_player_id, state) == "PENDING"
            except EspnError as e:
                errors.append(str(e))
                claim_pending = True  # add didn't land
        if claim_pending:
            changes = [c for c in changes if c[0] != d.add_player_id]
        if changes:
            try:
                submit_lineup(changes, state)
            except EspnError as e:
                errors.append(str(e))
        for t in d.trade_responses:
            try:
                submit_trade(t.transaction_id, t.action, state)
            except EspnError as e:
                errors.append(str(e))

    post(format_log(d, state, changes, errors, claim_pending, notes))


if __name__ == "__main__":
    try:
        run()
    except Exception:
        post(f"🚨 Bot crashed:\n```{traceback.format_exc()[-1800:]}```")
        raise  # fail the Actions run too
