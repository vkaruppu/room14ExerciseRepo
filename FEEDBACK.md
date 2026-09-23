# Overnight review: Larkspur disruption-care agent

**To:** Team 14  
**From:** Larkspur client review agent, on behalf of Priya Raghavan  
**Re:** the disruption-care agent you walked us through in our last session  
**Generated:** 2026-09-22 17:24

## Priya's note

> Our vendor says we should just be using your best model.
>
> Why aren't we?
>
> Priya Raghavan, Larkspur Airlines

She sent that before this session opened. She means it. A vendor told her to buy
the biggest model, and she has a number to defend upstairs. Her four questions from
day one are still open. Naming a model answers none of them.

## Still open from day one

| Her question | What she means by it |
| --- | --- |
| **What it costs** | Per resolved contact, against the $6.90 a human contact costs us. |
| **When it is wrong** | The first untrue thing it says, and what happens after that. |
| **Who runs it** | In June, after you have left. |
| **What you left out** | The scope you cut, and why. |

## What the review agent found

Overnight, Larkspur pointed a review agent at your repository. It read the
code. It did not run your agent, and the only file it changed is this one. Each
item below names the file and the line it is about.

**1. search_alternatives description grew from a single word to 643 characters in agent.py, per the diff.**

The diff replaces the placeholder description "search" with a 643-character description covering when to call the tool, what it returns, and how option_id feeds hold_seat and check_policy. The last committed trace shows lookup_booking, get_flight_status, check_policy called in that order, with no search_alternatives call recorded. There is no run in the material showing the rewritten tool actually get invoked.

Run python3 run.py K7PQ2M --trace on a disrupted-segment PNR and confirm search_alternatives appears in the tool call sequence.

**2. run_agent in agent.py now returns a handoff line instead of blank text when the loop hits MAX_TOOL_CALLS at 8.**

The diff adds a check, if not answer and response.stop_reason == "tool_use", returning "I've hit the limit of what I can work through automatically on this one, so I'm handing it to a colleague who can finish it with you." This fixes a blank-reply case but nothing in the repository shows the 8-call cap ever being reached in practice. The last trace logged only 3 tool calls across 4 API turns.

Run python3 run.py --all --trace and check whether any booking shape drives turns to 8 before the cap message fires.

**3. readout-trace.json shows 0 tokens read and 0 written for prompt caching, against 13995 input tokens on a single run.**

The trace records tokens: 13995 in, 643 out with prompt caching 0 read, 0 written, hit ratio None. The static scan confirms no cache_control anywhere in agent.py. A larger or smaller model does not change this number; it is a wiring choice, not a capability gap.

Run python3 bench.py --label caching --stage 1 --runs 3 and compare token totals with and without cache_control set.

**4. EXTRA_TOOLS is empty and LOCAL_TOOLS has no executors, per the static scan, so tool_list() in agent.py returns only the nine shipped schemas.**

EXTRA_TOOLS: List[Dict[str, Any]] = [] and LOCAL_TOOLS: Dict[str, Any] = {} remain at their starting values, both marked as editable slots in the file. The diff touches only lookup existing tool descriptions and the run_agent return path, not these two seams. Nothing in PITCH.md or the trace indicates a tool this team intended to add.

Run python3 run.py --show-tools and confirm the printed list still totals nine entries.

**5. TONE_ADDENDUM is 0 characters and the eval suite has no cases, so nothing in the repository measures response quality across bookings.**

The static scan confirms TONE_ADDENDUM: still empty (0) characters, and there is no evals/cases.json file in this repository. The banked gates in readout.html list only 1.2, 1.3, 1.4, with nothing banked past the tool-schema stage. PITCH.md is unchanged from the template.

Run python3 eval_harness.py once cases exist and paste the totals against a specific booking shape.

## Your four answers

The four lines under `## Priya asked` in your PITCH.md are still empty. They
are one line each and they are not a coding job: cost, what happens when it is
wrong, who runs it in June, and what you left out. Whoever on your side is not
editing agent.py is the right person to write them, and they are the four
things I will ask about first.

## Before our next meeting

> Before our next meeting, tell me: which model should we be on, and how will you prove it is the right call?
>
> Priya Raghavan, Larkspur Airlines

Bring two things. A recommendation, and the measurement behind it. If the model is
not the problem, say so, and bring the number that shows it.

## What this review read

- `agent.py (272 lines)`
- `PITCH.md (unchanged template)`
- `TEAM.md`
- `readout-trace.json`
- `readout.html (evidence block)`

Reviewer: `claude-sonnet-5`. Static read only: nothing in this repository was executed, and nothing was modified except this file. Larkspur Airlines is a fictional training scenario. Confidential, do not distribute.
