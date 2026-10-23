"""validate.py - legality checks only. Bad-but-legal moves pass."""
from collections import Counter

CAPACITY = {"PG": 1, "SG": 1, "SF": 1, "PF": 1, "C": 1, "G": 1, "F": 1,
            "UTIL": 3, "BE": 3, "IR": 1}
STARTERS = set(CAPACITY) - {"BE", "IR"}
MAX_ROSTER = 13
MAX_C = 4


def validate(d, state):
    """Return None if legal, else an error string to send back to Gemini."""
    errs = []
    roster = {p["id"]: p for p in state["roster"]}
    fas = {p["id"]: p for p in state["free_agents"]}
    name = lambda pid: (roster.get(pid) or fas.get(pid) or {}).get("name", pid)

    # Add / drop
    if d.add_player_id is not None:
        if d.add_player_id not in fas:
            errs.append(f"add {d.add_player_id} is not in the free agent list")
        if state["adds_used"] >= state["adds_limit"]:
            errs.append("no adds left this matchup")
    if d.drop_player_id is not None and d.drop_player_id not in roster:
        errs.append(f"drop {d.drop_player_id} is not on your roster")
    if roster.get(d.drop_player_id, {}).get("locked"):
        errs.append(f"{name(d.drop_player_id)} is locked (game started) and can't be dropped")

    after = {k: v for k, v in roster.items() if k != d.drop_player_id}
    if d.add_player_id in fas:
        after[d.add_player_id] = fas[d.add_player_id]
    if len(after) > MAX_ROSTER:
        errs.append(f"roster would have {len(after)} players (max {MAX_ROSTER}); drop someone to add")
    if sum(p["pos"] == "C" for p in after.values()) > MAX_C:
        errs.append(f"roster would have more than {MAX_C} centers")

    # Lineup coverage
    ids = [a.player_id for a in d.lineup]
    for pid, n in Counter(ids).items():
        if n > 1:
            errs.append(f"{name(pid)} assigned {n} times")
    for pid in set(ids) - set(after):
        errs.append(f"{pid} in lineup but not on roster")
    for pid in set(roster) - {d.drop_player_id} - set(ids):
        errs.append(f"{name(pid)} has no slot; every roster player needs one")

    # Slot capacity
    for slot, n in Counter(a.slot for a in d.lineup).items():
        if n > CAPACITY[slot]:
            errs.append(f"{n} players in {slot} (max {CAPACITY[slot]})")

    # Eligibility + injuries
    for a in d.lineup:
        p = after.get(a.player_id)
        if not p:
            continue
        if a.slot == "IR" and p["injury"] != "OUT":
            errs.append(f"{p['name']} on IR but status is {p['injury']}, not OUT")
        elif a.slot not in ("BE", "IR") and a.slot not in p["eligible"]:
            errs.append(f"{p['name']} not eligible for {a.slot} (eligible: {p['eligible']})")
        if a.slot in STARTERS and p["injury"] == "OUT" and not p.get("locked"):
            errs.append(f"{p['name']} is OUT and can't start")
        if p.get("locked") and a.player_id in roster and a.slot != p["slot"]:
            errs.append(f"{p['name']} is locked (game started) and must stay in {p['slot']}")

    # Trades (pending is already filtered to offers sent to us)
    offered = {str(t["id"]) for t in state["pending"]}
    for t in d.trade_responses:
        if t.transaction_id not in offered:
            errs.append(f"trade {t.transaction_id} is not a pending offer")

    return "; ".join(errs) or None


def decide_valid(state, max_retries=2):
    """Decide, validate, retry with error feedback. Returns (decision, error)."""
    from decide import decide
    err = None
    for _ in range(max_retries + 1):
        d = decide(state, err)
        err = validate(d, state)
        if err is None:
            return d, None
    return None, err  # skip the day


if __name__ == "__main__":
    import json
    from state import gather
    d, err = decide_valid(gather())
    print(json.dumps(d.model_dump(), indent=2) if d else f"SKIPPED: {err}")
