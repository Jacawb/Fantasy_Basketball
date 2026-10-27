"""lineup.py - deterministic safety net for the lineup.

Starting a player who doesn't play today over one who does is never better,
so this only overrides Gemini there. It also builds a full lineup when Gemini
can't produce a legal one, so a day is never skipped.
"""
from validate import CAPACITY, STARTERS

STARTER_SLOTS = [s for s in CAPACITY if s in STARTERS for _ in range(CAPACITY[s])]


def _match(players, slots, prefer):
    """Fit players into slots by eligibility. Returns {pid: slot} or None."""
    by_id = {p["id"]: p for p in players}
    owner = {}  # slot index -> pid

    def place(p, seen):
        # try the preferred slot first so the lineup changes as little as possible
        for i in sorted(range(len(slots)), key=lambda i: slots[i] != prefer.get(p["id"])):
            if slots[i] in p["eligible"] and i not in seen:
                seen.add(i)
                if i not in owner or place(by_id[owner[i]], seen):
                    owner[i] = p["id"]
                    return True
        return False

    for p in players:
        if not place(p, set()):
            return None
    return {pid: slots[i] for i, pid in owner.items()}


def solve(state, add_id=None, drop_id=None, prefer=None):
    """Legal lineup {pid: slot} for the roster after add/drop, or None.

    Starters are picked in order: plays today, in a starting slot in `prefer`
    (Gemini's lineup, else the current one), then season average.
    """
    roster = {p["id"]: p for p in state["roster"]}
    fas = {p["id"]: p for p in state["free_agents"]}
    players = [p for pid, p in roster.items() if pid != drop_id]
    if add_id in fas:
        players.append(fas[add_id])
    if prefer is None:
        prefer = {pid: p["slot"] for pid, p in roster.items()}

    out, free, cap = {}, list(STARTER_SLOTS), {"BE": CAPACITY["BE"], "IR": CAPACITY["IR"]}
    for p in players:  # locked players stay where they are
        if p["id"] in roster and p.get("locked"):
            out[p["id"]] = p["slot"]
            if p["slot"] in cap:
                cap[p["slot"]] -= 1
            elif p["slot"] in free:
                free.remove(p["slot"])
    rest = [p for p in players if p["id"] not in out]

    rank = sorted((p for p in rest if p["injury"] != "OUT"),
                  key=lambda p: (not p["plays_today"], prefer.get(p["id"]) not in STARTERS, -p["avg"]))
    starters = []
    for p in rank:  # greedy is optimal here: feasible starter sets form a matroid
        if _match(starters + [p], free, prefer) is not None:
            starters.append(p)
    out.update(_match(starters, free, prefer))

    # Everyone else to BE; OUT players go to IR if Gemini put them there or BE is full
    left = [p for p in rest if p["id"] not in out]
    left.sort(key=lambda p: prefer.get(p["id"]) != "IR")
    for p in left:
        if p["injury"] == "OUT" and cap["IR"] and (prefer.get(p["id"]) == "IR" or len(left) > cap["BE"]):
            out[p["id"]], cap["IR"] = "IR", cap["IR"] - 1
    for p in left:
        if p["id"] not in out:
            out[p["id"]], cap["BE"] = "BE", cap["BE"] - 1
    return out if cap["BE"] >= 0 else None


def autostart(lineup, state, add_id=None, drop_id=None):
    """Gemini's lineup {pid: slot}, with anyone who plays today moved in for a
    starter who doesn't. Returns (lineup, ids newly started)."""
    fixed = solve(state, add_id, drop_id, prefer=lineup)
    if fixed is None:
        return lineup, []
    starters = {pid for pid, s in lineup.items() if s in STARTERS}
    gained = [pid for pid, s in fixed.items() if s in STARTERS and pid not in starters]
    return (fixed, gained) if gained else (lineup, [])
