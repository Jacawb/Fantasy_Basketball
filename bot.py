"""bot.py - daily loop: gather -> decide -> validate -> submit -> log."""
import os
import traceback

from notify import post
from state import gather
from validate import decide_valid

# Stays True until ESPN write endpoints are captured and wired in
DRY_RUN = os.getenv("DRY_RUN", "true").lower() != "false"


# --- ESPN writes (fill in after draft) ---
def submit_add_drop(add_id, drop_id, state):
    raise NotImplementedError("capture add/drop + waiver endpoints")


def submit_lineup(changes, state):
    raise NotImplementedError("capture lineup endpoint")


def submit_trade(tx_id, action, state):
    raise NotImplementedError("capture trade accept/decline endpoint")


# --- helpers ---
def lineup_changes(d, state):
    """Only the moves that differ from the current lineup."""
    current = {p["id"]: p["slot"] for p in state["roster"]}
    return [(a.player_id, current.get(a.player_id), a.slot)
            for a in d.lineup if current.get(a.player_id) != a.slot]


def format_log(d, state, changes):
    names = {p["id"]: p["name"] for p in state["roster"] + state["free_agents"]}
    n = lambda pid: names.get(pid, pid)
    m = state.get("matchup") or {}
    lines = [f"**{state['date']}** | matchup {state['matchup_period']} | "
             f"adds {state['adds_used']}/{state['adds_limit']}"]
    if "my_score" in m:
        lines.append(f"vs {m['opponent']}: {m['my_score']} - {m['opp_score']}")
    if d.add_player_id:
        lines.append(f"➕ Add {n(d.add_player_id)}")
    if d.drop_player_id:
        lines.append(f"➖ Drop {n(d.drop_player_id)}")
    for pid, old, new in changes:
        lines.append(f"🔁 {n(pid)}: {old or 'new'} → {new}")
    for t in d.trade_responses:
        lines.append(f"🤝 Trade {t.transaction_id}: {t.action}")
    if len(lines) == (2 if "my_score" in m else 1):
        lines.append("No moves today")
    lines.append(f"\n> {d.reasoning}")
    if DRY_RUN:
        lines.insert(0, "🧪 DRY RUN (nothing submitted)")
    return "\n".join(lines)


def run():
    state = gather()
    d, err = decide_valid(state)
    if d is None:
        post(f"⚠️ {state['date']}: skipped day, invalid after retries:\n{err}")
        return

    changes = lineup_changes(d, state)
    if not DRY_RUN:
        # Add/drop first so the lineup can use the new player
        if d.add_player_id or d.drop_player_id:
            submit_add_drop(d.add_player_id, d.drop_player_id, state)
        if changes:
            submit_lineup(changes, state)
        for t in d.trade_responses:
            submit_trade(t.transaction_id, t.action, state)

    post(format_log(d, state, changes))


if __name__ == "__main__":
    try:
        run()
    except Exception:
        post(f"🚨 Bot crashed:\n```{traceback.format_exc()[-1800:]}```")
        raise  # fail the Actions run too
