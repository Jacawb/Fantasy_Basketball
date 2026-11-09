"""smoke.py - quick startup check the workflow runs before the bot.

Loads every module and reads league state from ESPN. No Gemini call, no ESPN
writes, no Discord post. A non-zero exit means the installed package versions
can't run the bot, so the workflow falls back to requirements.lock.
"""
import bot  # noqa: F401  (imports decide, lineup, notify, state, validate)
import decide
from google.genai import errors, types
from state import gather

# The pieces of the Gemini SDK the bot relies on
assert callable(decide.client.models.generate_content)
assert types.GenerateContentConfig and types.HttpOptions
assert errors.ServerError and errors.ClientError
assert decide.TRANSPORT_ERRORS, "no httpx/httpx2 transport errors to retry on"

state = gather()
assert state["roster"], "ESPN returned an empty roster"
print(f"smoke ok: {len(state['roster'])} roster players, "
      f"{len(state['free_agents'])} free agents, models {decide.MODELS}")
