# PITCH.md

Six lines and a lever. Your words. The last two are scored.

Built: The loop in agent.py and the twelve tool descriptions Claude reads before it picks one — Larkspur's nine existing tools wired up, reopen_stats written by us over the handled-transcript sample, and next_available_day and fare_rules moved onto our own MCP server so the model cannot tell which program answers.
Does: A stranded customer sends one message; the agent looks up the booking, reads live flight status, resolves what policy actually owes them, and comes back with named alternatives, times and seats left — then stops and asks which one to hold, because nothing moves until the customer picks.
Number: Our tool list costs 5,053 tokens on every turn, up from 3,650 before we finished the descriptions — +1,403 tokens per API turn, 12 tools, counted on the wire by run.py --tool-tax, and paid on turns where no tool fires at all. The five ticket types resolve 5 of 5 at roughly 24,000 input tokens per contact, 12.3s each.
Safety check: confirm_rebooking is the only irreversible tool and it cannot be reached from chat — the token is minted by the customer's Confirm click and the backend rejects anything else. We proved the agent respects that rather than arguing round it: on today's K7PQ2M cancellation trace it makes 4 tool calls, stops at search_alternatives, and asks which option to hold.
Next: Build the proof we skipped — our own eval cases through eval_harness.py, so accuracy is a measured number instead of five traces that looked fine; then pick the lever and bench before and after it.
Still broken: Nothing watches tone on the way in — R8KD3F is an abusive message and it gets the same calm, helpful answer, with no flag and no escalation; and reopen_stats, the tool we wrote and described as a routine step on every contact, fired on neither trace we ran today.
Lever: <cost | speed | intelligence>

## Priya asked

Costs:
Wrong:
Runs it:
Left out:
