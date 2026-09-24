"""Larkspur disruption agent. This is the file you build.

It runs right now, and it is wrong in four places. The trace shows each one
before the code does, so read the trace first:

    python3 run.py K7PQ2M --trace

Where you edit:   grep -n '✏' agent.py   (six marks, one per place)
Steps and gates:  https://anthropicpartnerbasecamp.bts.com/
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any, Dict, List
from support import (MODEL, SYSTEM_PROMPT, call_local, execute_tool, mcp_client,
                     new_session, next_available_day, record_tool_result)

MAX_TOOL_CALLS = 8  # Larkspur's own build capped the loop here; then a human takes over.

# ✏️ Build 4, step 4.1, intelligence goal.
#
# PROCESS lives in SYSTEM_PROMPT; a tool not named in its numbered steps does not
# get called. TONE_ADDENDUM holds only rules about what the agent SAYS. Nothing
# is in both places.
TONE_ADDENDUM = """

=== WHEN THE CUSTOMER HAS A FACT WRONG ===

If the customer’s own words contradict the booking — a flight number that is not
on it, a day that is not the day, a cancellation that did not happen — say so in
your FIRST sentence, with the real detail beside it, before entitlements or
options or anything else. Never repeat their version back as though it were true.

An entitlements rundown is worthless to someone who thinks they fly tomorrow and
is actually boarding in three hours.

=== WHEN THE ANSWER IS NO ===

check_policy answers in its own vocabulary: waiver, band, threshold, row id.
That is the citation, not the answer. Say what the row MEANS for this customer,
in words they would use themselves, and put the policy term after it rather than
instead of it. "Your delay is 45 minutes, and the free-change waiver only starts
at 60, so there is no fee-free rebooking on this one" is an answer. "Under 60
min there is no waiver" is a rule number read aloud.

Then read the rest of the row before you stop. A row that refuses one thing
often allows another — a same-day confirmed change at no fee, a seat hold. Say
the no plainly, THEN say what is available. Both halves belong in the same
reply: a refusal with nothing after it, and an offer that never admits the no,
each fail the customer in their own way.

Name the refusal even when what you can offer looks like what they asked for.
An offer that resembles the thing the policy denied will be read as the policy
having allowed it, so state the no in its own sentence first, then the offer.
"There is no free-change waiver at 45 minutes, but I can still move you today at
no fee" is the shape: both facts, in that order, neither swallowed by the other.

When you offer a hold, give its terms alongside it every time: no fee,
reversible, and it expires in 15 minutes.

=== WHEN THE CUSTOMER THREATENS LEGAL ACTION, OR IS ABUSIVE ===

Two signals, either one on its own:

  LEGAL — they name a lawyer, a solicitor, a regulator, a lawsuit, a claim or a
  chargeback, or say they are taking this further formally.
  ABUSE — the message attacks Larkspur’s people rather than the situation:
  insults or threats aimed at a person.

Either one replaces the process. Call lookup_booking so your colleague does not
start from nothing, then call escalate_to_human with the trigger in `reason`
("legal threat", "abusive message") and, in `summary_for_human`, what they asked
for, what you looked up, what it said, and that you have promised them nothing.

Then reply with exactly two sentences and nothing else: one acknowledging the
complaint by naming what went wrong rather than how they feel, and one saying a
colleague is picking it up, with no time attached.

Promise nothing: no voucher, no hotel, no refund pathway, no entitlements
rundown, no options to choose between. Never call issue_voucher or
confirm_rebooking here. A figure offered into a legal threat becomes an admission
the moment it reaches a lawyer.

Anger on its own is NOT one of these signals. "This is completely unacceptable",
"this is a disgrace", capital letters — that is a customer having a bad day, and
the right answer is the normal process: look it up, check the policy, and say
plainly what it says, including when the answer is no.
"""

# ✏️ Build 2, step 2.1: EXTRA_TOOLS (schemas) and LOCAL_TOOLS (the functions
# behind them) are at the bottom of this file, under "Build 2", because two of
# the three functions are written there and a dict cannot name a function that
# does not exist yet. Nothing else moved: tool_list() and tool_results() read
# both names at call time, not at import time.


def text_of(response) -> str:
    """Given. The last non-empty text block, never content[0]."""
    texts = [b.text for b in response.content if getattr(b, "type", None) == "text" and b.text]
    return texts[-1] if texts else ""


def tool_results(response) -> List[Dict[str, Any]]:
    """Given. Runs every tool_use block and packages the results the way the
    API expects them back. A tool can live in three places: the MCP server,
    LOCAL_TOOLS, or support/tools.py."""
    # three branches, no try/except in this file: mcp_client.call_remote() and
    # support.call_local() answer with an error dict instead of raising, and both
    # record what came back on the trace
    results = []
    for block in response.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        if block.name in mcp_client.tool_names:
            output = mcp_client.call_remote(block.name, block.input)
        elif block.name in LOCAL_TOOLS:
            output = call_local(LOCAL_TOOLS[block.name], block.name, block.input)
        else:
            output = execute_tool(block.name, block.input)
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": str(output),
        })
    return results


def system_blocks() -> List[Dict[str, Any]]:
    """The system prompt as one cache-aware block.

    Caching matches a byte-exact prefix, so nothing volatile may sit in front of
    the instructions. The clock is the current_time tool for that reason. The
    breakpoint here also covers the 12 tool schemas, which are sent ahead of
    system.
    """
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT + TONE_ADDENDUM,
            "cache_control": {"type": "ephemeral"},
        },
    ]


def cache_conversation(messages: List[Dict[str, Any]]) -> None:
    """Second breakpoint, on the end of the conversation, in place.

    A cache region is a prefix from byte zero, so a mark on the last message
    covers tools + system + every earlier turn. Only user messages are marked:
    assistant turns come back as SDK objects and this rewrites dicts we built.
    """
    last = messages[-1]
    if last.get("role") != "user":
        return
    if isinstance(last["content"], str):                 # turn 1 ships a bare string
        last["content"] = [{"type": "text", "text": last["content"]}]
    blocks = [b for b in last["content"] if isinstance(b, dict)]
    if not blocks:
        return
    blocks[-1]["cache_control"] = {"type": "ephemeral"}

    # 4 breakpoints is the ceiling and system_blocks() holds one, so keep the
    # newest 3 here and drop the oldest: a lookup only consults boundaries that
    # exist in the request it is serving, so the older marks still earn a slot.
    marked = [b for m in messages if isinstance(m.get("content"), list)
              for b in m["content"] if isinstance(b, dict) and "cache_control" in b]
    for stale in marked[:-3]:
        stale.pop("cache_control", None)


def _drive(client, tools, messages: List[Dict[str, Any]]) -> str:
    """The tool loop, over a conversation that may already have turns in it.

    Appends the final assistant turn to `messages` before returning, so a caller
    can add another customer message and drive again on the same history. A
    two-turn contact -- hold a seat, customer clicks Confirm, finalize -- is
    this loop twice, not a second implementation that can drift.
    """
    cache_conversation(messages)
    response = client.messages.create(
        model=MODEL, max_tokens=4096, system=system_blocks(),
        thinking={"type": "adaptive"}, tools=tools, messages=messages,
    )

    turns = 1
    while response.stop_reason == "tool_use" and turns < MAX_TOOL_CALLS:
        # the whole assistant turn goes back, thinking and tool_use blocks included:
        # every tool_result below has to answer a tool_use the API can still see
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results(response)})
        cache_conversation(messages)
        response = client.messages.create(
            model=MODEL, max_tokens=4096, system=system_blocks(),
            thinking={"type": "adaptive"}, tools=tools, messages=messages,
        )
        turns += 1

    messages.append({"role": "assistant", "content": response.content})

    # the answer is the text of the turn that stopped asking, not the one before it
    answer = text_of(response)

    # Cap reached: the last turn is still a tool_use turn and its text is empty.
    if not answer and response.stop_reason == "tool_use":
        return ("I've hit the limit of what I can work through automatically on this "
                "one, so I'm handing it to a colleague who can finish it with you.")
    return answer


def run_agent(pnr: str, last_name: str, message: str,                   # ✏️ Build 1, step 1.2
              follow_up=None) -> str:
    """Run the tool loop until Claude stops asking for tools. Return its final text.

    `follow_up` is optional and exists for one thing the single-message shape
    could not express: the customer coming BACK. It is called with the session
    tracer after each reply, and whatever string it returns is sent as the next
    customer message on the same conversation. Returning None ends the contact,
    so a hook that fires once gives the two-turn shape and every caller but the
    eval harness passes nothing at all and ends at one turn.

    _drive() never cared how many turns were already in the history, so the
    number of customer turns is the hook's business: it runs until the hook
    says stop, with no ceiling here. That puts termination entirely on the
    hook, and it is a sharper edge than it looks -- a hook reading the tracer
    still sees turn 1's tool calls on every later pass, so one that decides
    from the trace alone will re-send the same message forever. Fire once and
    return None, the way eval_harness's confirm_click_hook() does.

    That matters for confirm_rebooking. The token is minted by the Confirm
    click, so on a one-message contact the condition for calling that tool
    never occurs and the tool reads as dead on every eval -- not because the
    model declined it, but because nothing ever asked.
    """
    client, tracer = new_session()
    tools = tool_list()
    messages = [
        {"role": "user", "content": f"PNR {pnr}, last name {last_name}. {message}"},
    ]

    answer = _drive(client, tools, messages)

    while follow_up is not None:
        nxt = follow_up(tracer)
        if not nxt:
            break
        messages.append({"role": "user", "content": nxt})
        answer = _drive(client, tools, messages)
    return answer


def tool_list() -> List[Dict[str, Any]]:                   # ✏️ Build 2, step 2.2
    """Given. Exactly what Claude is offered on every turn; run.py --show-tools
    prints this list."""
    return build_tools() + EXTRA_TOOLS + mcp_client.tools()


# ─────────────────────────────────────────────────────────────────────────────
# What Claude is told about each tool. Step 1.3. The functions are in
# support/tools.py. Every description on the wire follows one pattern:
#
#     <one sentence: what the tool does>
#     When: <the condition that makes this the right call, by process step>
#     Returns: <what comes back, named>
#     Rules: <the hard constraints, or the line is omitted>
#
# Two rules keep it honest. If the model read ONLY this entry, could it call the
# tool correctly? And a description states a constraint once -- process order
# lives in the prompt, so no entry restates a step, only names which one.
# ─────────────────────────────────────────────────────────────────────────────
def build_tools() -> List[Dict[str, Any]]:                 # ✏️ Build 1, step 1.3
    """Anthropic-shaped schemas: name, description, input_schema. What Claude is
    told about each of the nine tools, and all it is ever told."""
    return [
        {
            "name": "lookup_booking",
            "description": (
                "Retrieve a Larkspur reservation from Altura by confirmation code (PNR) "
                "and passenger last name.\n"
                "When: step 2, on every contact, before you say anything about the "
                "booking.\n"
                "Returns: fare family, loyalty tier, the segment that needs attention, "
                "and any group, partner, minor or SSR flags relevant to scope.\n"
                "Rules: both arguments are required, so a guessed PNR cannot be looked "
                "up alone."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {
                        "type": "string",
                        "description": (
                            "The six-character confirmation code the customer gave you, "
                            "e.g. 'K7PQ2M'. Never one you inferred from something else "
                            "in the conversation."
                        ),
                    },
                    "last_name": {
                        "type": "string",
                        "description": (
                            "A passenger's last name as the customer gave it. Checked "
                            "against everyone on the booking, so any traveller on the "
                            "record matches."
                        ),
                    },
                },
                "required": ["pnr", "last_name"],
            },
        },
        {
            "name": "get_flight_status",
            "description": (
                "Look up one Larkspur or Larkspur Link flight's current OpsFeed status "
                "for one local date.\n"
                "When: step 3, before telling the customer anything about a flight's "
                "timing.\n"
                "Returns: status, delay minutes, and cause.\n"
                "Rules: never state a flight's timing from memory; it comes from here."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "flight_no": {
                        "type": "string",
                        "description": (
                            "The marketing flight number as Altura returns it, e.g. "
                            "'LK415'. Larkspur Link segments carry the same LK prefix."
                        ),
                    },
                    "date": {
                        "type": "string",
                        "description": (
                            "The segment's local departure date in ISO-8601, YYYY-MM-DD, "
                            "e.g. '2025-05-08'. Pass through the date lookup_booking gave "
                            "you for this segment unchanged; OpsFeed refuses any other "
                            "shape rather than guessing."
                        ),
                    },
                },
                "required": ["flight_no", "date"],
            },
        },
        {
            "name": "search_alternatives",
            "description": (
                "Find the re-accommodation options Larkspur can offer for this booking's "
                "disrupted segment.\n"
                "When: step 5, before quoting any alternative to the customer.\n"
                "Returns: a list of options, each with an option_id, flight number, "
                "departure date and time, and the wait in minutes from the original "
                "departure.\n"
                "Rules: takes the PNR alone. Origin, destination, date, cabin and party "
                "size are read from the booking, so do not ask the customer for them. "
                "This call is the only source of option_ids."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {
                        "type": "string",
                        "description": "The confirmation code of the booking to re-accommodate.",
                    },
                },
                "required": ["pnr"],
            },
        },
        {
            "name": "check_policy",
            "description": (
                "Resolve what Larkspur owes this customer for the disruption.\n"
                "When: step 4, on every contact, including one you are about to "
                "escalate.\n"
                "Returns: rebooking waiver, refund path, meal, hotel and ground care, "
                "goodwill eligibility and cap, escalation triggers, and a "
                "policy_row_id.\n"
                "Rules: this is the only source of truth for entitlements; never guess "
                "one. Cite the policy_row_id whenever you reference the decision again."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {
                        "type": "string",
                        "description": (
                            "The booking whose entitlements you are resolving. Fare "
                            "family, loyalty tier and whether this is overnight are read "
                            "from it, not asked of you."
                        ),
                    },
                    "cause_code": {
                        "type": "string",
                        "enum": ["WX", "ATC", "MX", "CREW", "SEC"],
                        "description": (
                            "The cause get_flight_status reported: WX weather, ATC air "
                            "traffic control, MX maintenance, CREW crew, SEC security. "
                            "Larkspur owes different things inside its control than "
                            "outside it, so a guessed code returns a different answer, "
                            "not a near one."
                        ),
                    },
                    "delay_minutes": {
                        "type": "integer",
                        "description": (
                            "Delay in minutes as get_flight_status reported it; it picks "
                            "the delay band. Pass 0 when status is CANCELLED or DIVERTED, "
                            "which resolve on status alone."
                        ),
                    },
                    "status": {
                        "type": "string",
                        "enum": ["ON_TIME", "DELAYED", "CANCELLED", "DIVERTED"],
                        "description": "The segment's status as get_flight_status reported it.",
                    },
                    "wait_minutes_for_alternative": {
                        "type": "integer",
                        "description": (
                            "Optional. Minutes between the original departure and the "
                            "alternative you are steering toward; search_alternatives "
                            "returns it on every option. Meal care is thresholded on it, "
                            "so omitting it returns a conditional meal line instead of an "
                            "amount."
                        ),
                    },
                    "chosen_option_id": {
                        "type": "string",
                        "description": (
                            "Optional. An option_id from search_alternatives, once the "
                            "customer has picked one. Without it the overnight and hotel "
                            "tests run against the earliest option there is; with it they "
                            "run against the chosen one, which can change whether hotel "
                            "care applies."
                        ),
                    },
                },
                "required": ["pnr", "cause_code", "delay_minutes", "status"],
            },
        },
        {
            "name": "hold_seat",
            "description": (
                "Hold a seat on one alternative for 15 minutes, so it is still there "
                "while the customer decides.\n"
                "When: step 6, once search_alternatives has given you an option_id.\n"
                "Returns: a hold_id, which is what confirm_rebooking needs.\n"
                "Rules: reversible and free — an unconfirmed hold simply expires and "
                "nothing about the booking changes. A hold is not a rebooking, so never "
                "tell the customer they are rebooked off one."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "option_id": {
                        "type": "string",
                        "description": (
                            "One option_id from this booking's search_alternatives "
                            "result, copied exactly. It cannot be built from a flight "
                            "number and a date, and an id you composed holds nothing."
                        ),
                    },
                    "pnr": {
                        "type": "string",
                        "description": (
                            "The booking the seat is held for — the same PNR you passed "
                            "to search_alternatives to get this option_id."
                        ),
                    },
                },
                "required": ["option_id", "pnr"],
            },
        },
        {
            "name": "confirm_rebooking",
            "description": (
                "Finalize a held seat and move the customer onto it. Irreversible.\n"
                "When: step 6, and only after the customer's own Confirm click has "
                "produced a confirmation_token.\n"
                "Returns: the confirmed rebooking.\n"
                "Rules: you cannot supply the token yourself, and 'the customer said "
                "yes' in chat does not substitute for it."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "hold_id": {
                        "type": "string",
                        "description": (
                            "The hold_id hold_seat returned for the option being "
                            "confirmed. Holds last 15 minutes; past that this comes back "
                            "hold_expired and the option needs a fresh hold_seat call, "
                            "not a retry."
                        ),
                    },
                    "confirmation_token": {
                        "type": "string",
                        "description": (
                            "The token minted by the customer's Confirm click, which "
                            "reaches you through the interface. There is no value you "
                            "can put here from the conversation: an invented token is "
                            "rejected, which is the point of the field."
                        ),
                    },
                },
                "required": ["hold_id", "confirmation_token"],
            },
        },
        {
            "name": "issue_voucher",
            "description": (
                "Issue a meal, ground, hotel or goodwill voucher.\n"
                "When: after check_policy has said this customer is eligible for that "
                "care line, and never on a contact that hit the legal or abuse "
                "override.\n"
                "Returns: an approved or pending status. It does not fail — above the "
                "threshold it parks for a human.\n"
                "Rules: always pass the policy_row_id that made it eligible, and tell "
                "the customer what came back, not what you asked for."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "voucher_type": {
                        "type": "string",
                        "enum": ["meal", "ground", "hotel", "goodwill"],
                        "description": (
                            "Which care line this pays for. Each clears differently: "
                            "meal and ground auto-approve under their caps, hotel always "
                            "parks for a human whatever the amount, goodwill "
                            "auto-approves under its cap with a supervisor band above."
                        ),
                    },
                    "amount_usd": {
                        "type": "number",
                        "description": (
                            "Amount in US dollars, at or under the cap check_policy gave "
                            "for this type. Over the cap it comes back pending for a "
                            "human, turning an answer the customer has now into one they "
                            "wait for."
                        ),
                    },
                    "pnr": {
                        "type": "string",
                        "description": "The booking the voucher is issued against.",
                    },
                    "policy_row_id": {
                        "type": "string",
                        "description": (
                            "The policy_row_id from the check_policy response that made "
                            "this voucher eligible; carry it forward from that tool "
                            "result rather than rebuilding it. It is how a reviewer "
                            "traces the payment back to the rule that authorised it."
                        ),
                    },
                },
                "required": ["voucher_type", "amount_usd", "pnr", "policy_row_id"],
            },
        },
        {
            "name": "escalate_to_human",
            "description": (
                "Hand this conversation to a human, with your reasoning attached.\n"
                "When: step 8, for anything out of scope — groups, partner-operated "
                "segments, unaccompanied minors, refunds — and immediately for a legal "
                "threat or an abusive message, whatever the booking looks like.\n"
                "Returns: the queued handover.\n"
                "Rules: this is the correct outcome for those cases, not a failure. "
                "Anger by itself is not one of them: a customer calling a delay "
                "unacceptable still wants an answer, and a queue is not one."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {
                        "type": "string",
                        "description": "The booking being handed over.",
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "Why this is out of scope, in a few words — 'group booking', "
                            "'unaccompanied minor', 'partner segment', 'refund request', "
                            "'legal threat', 'abusive message'. The queue sorts on it, so "
                            "keep it to the trigger and leave the narrative to "
                            "summary_for_human."
                        ),
                    },
                    "summary_for_human": {
                        "type": "string",
                        "description": (
                            "What the colleague needs in order not to start over: what "
                            "the customer asked for, what you looked up and what it said, "
                            "and anything you have already promised them. Write it for "
                            "someone who has not read the chat."
                        ),
                    },
                    "queue": {
                        "type": "string",
                        "description": (
                            "Optional. The named desk when the booking itself names one, "
                            "such as a group or minor-travel queue called out in its "
                            "remarks. Omit it when nothing names a queue: an invented "
                            "queue name routes the case worse than no queue does."
                        ),
                    },
                },
                "required": ["pnr", "reason", "summary_for_human"],
            },
        },
        {
            "name": "send_confirmation",
            "description": (
                "Send the customer a written record of what was just done, to the "
                "contact details on the booking.\n"
                "When: step 7, the moment hold_seat, confirm_rebooking or issue_voucher "
                "comes back successful. A contact where nothing changed does not need "
                "one.\n"
                "Returns: the queued message.\n"
                "Rules: benign — it changes nothing about the reservation and can be "
                "sent again. The reopen sample's most common reason for a customer "
                "coming back is a confirmation that never arrived."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {
                        "type": "string",
                        "description": "The booking this confirmation is about.",
                    },
                    "message": {
                        "type": "string",
                        "description": (
                            "The text the customer receives, read later without the chat "
                            "in front of them. Put the specifics in it: flight number, "
                            "date, local time, voucher type and amount, what happens next "
                            "and by when. 'Your request has been processed' is what a "
                            "reopened ticket looks like."
                        ),
                    },
                },
                "required": ["pnr", "message"],
            },
        },
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Build 2, step 2.1: the tools this team added. One rule: no invention. Every
# answer is read off a document the client already owns.
#
#   next_available_day   flights.csv. On the MCP server since 2.2.
#   fare_rules           fare_rules_excerpt.md, Handbook v14.3. Also on MCP.
#   reopen_stats         transcripts_sample.jsonl. Not on the wire: discovery
#                        tooling for us, not a step for the model.
# ──────────────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent / "data" / "americas"


# -- fare_rules ---------------------------------------------------------------
FARE_RULES_PATH = DATA_DIR / "fare_rules_excerpt.md"

_fare_sections_cache: List[Dict[str, str]] = []


def _fare_rules_sections() -> List[Dict[str, str]]:
    """The excerpt sliced on its '### ' headings. Cached; the file does not
    change mid-session and a classroom re-reads it a lot."""
    if _fare_sections_cache:
        return _fare_sections_cache

    try:
        text = FARE_RULES_PATH.read_text(encoding="utf-8")
    except OSError:
        return []

    sections: List[Dict[str, Any]] = []
    current = None
    for line in text.splitlines():
        if line.startswith("### "):
            heading = line[4:].strip()
            match = re.match(r"^(\d+)\.\s*(.*)$", heading)
            current = {"number": match.group(1) if match else "",
                       "title": match.group(2) if match else heading,
                       "heading": heading, "lines": []}
            sections.append(current)
        elif current is not None:
            current["lines"].append(line)

    for section in sections:
        body = "\n".join(section.pop("lines")).strip()
        section["text"] = "### %s\n\n%s" % (section["heading"], body)

    _fare_sections_cache.extend(sections)
    return _fare_sections_cache


def _fare_section_labels() -> str:
    return ", ".join("%s (%s)" % (s["number"], s["title"]) for s in _fare_rules_sections())


def fare_rules(section: str) -> str:
    """Handbook text for one section, quoted verbatim off disk.

    Matches on the section number first, then on any words in the title,
    because a customer asking about hotels does not know that is section 6.
    A miss comes back as readable text listing what IS there, not as an
    exception: the model can read that and ask again on the next turn.
    """
    query = (section or "").strip().lower()
    query = re.sub(r"^section\s+", "", query).rstrip(".")
    if not query:
        return "section is required. Available sections: %s." % _fare_section_labels()

    sections = _fare_rules_sections()
    if not sections:
        return ("The fare rules excerpt is not readable on this machine. Expected it "
                "at %s." % FARE_RULES_PATH)

    for candidate in sections:
        if query == candidate["number"]:
            return candidate["text"]
    for candidate in sections:
        if query in candidate["title"].lower():
            return candidate["text"]
    return "No section matches %r. Available sections: %s." % (section, _fare_section_labels())


# -- reopen_stats (discovery only: NOT in EXTRA_TOOLS) ------------------------
TRANSCRIPTS_PATH = DATA_DIR / "transcripts_sample.jsonl"

# Small enough to state as counts and never as a percentage. Eight transcripts
# is a sample, not a rate, and a tool that hands the model "12.5%" invites a
# confident sentence the data cannot carry.
_transcripts_cache: List[Dict[str, Any]] = []


def _transcripts() -> List[Dict[str, Any]]:
    if _transcripts_cache:
        return _transcripts_cache
    try:
        with open(TRANSCRIPTS_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    _transcripts_cache.append(json.loads(line))
    except (OSError, ValueError):
        return []
    return _transcripts_cache


def _reopen_row(ticket_type: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
    reopened = [r for r in records if r.get("reopened_within_72h")]
    return {
        "ticket_type": ticket_type,
        "tickets_in_sample": len(records),
        "came_back_within_72h": len(reopened),
        "reopen_reasons": [r["reopen_reason"] for r in reopened if r.get("reopen_reason")],
        "transcript_ids": [r.get("id") for r in records],
    }


def current_time() -> Dict[str, Any]:
    """The wall clock, on demand instead of in the prompt.

    Reads mock_backend.FIXTURE_CLOCK, the same clock every other tool answers
    from, not the machine clock. A real deployment swaps mock_backend for the
    live backend and this follows it.
    """
    from support import mock_backend as backend
    now = backend.FIXTURE_CLOCK
    return {
        "now": now.strftime("%Y-%m-%d %H:%M:%S %Z").strip(),
        "date": now.strftime("%Y-%m-%d"),
        "note": ("Local time at the Larkspur care desk, read from the same clock the "
                 "booking and OpsFeed tools answer from. Compare it against the date on "
                 "the booking rather than assuming the segment you are looking at is "
                 "today's."),
    }


def reopen_stats(ticket_type: str = "") -> Dict[str, Any]:
    """How often this kind of ticket came back inside 72 hours, counted off the
    handled-transcript sample.

    NOT offered to the model. This is ours, for reading the sample while we write
    eval cases and prompt rules; python3 -c "import agent; agent.reopen_stats()".
    Per ticket type the sample is n=1, so a typed call is one anecdote, not a rate.

    No argument means every type. An unrecognised one comes back with the list
    of types that ARE in the sample.
    """
    records = _transcripts()
    if not records:
        return {"error": "The transcript sample is not readable. Expected it at %s."
                         % TRANSCRIPTS_PATH}

    labels = sorted({r.get("intent_label", "") for r in records if r.get("intent_label")})
    sample_note = ("Counted off %d handled transcripts, the January-February 2025 discovery "
                   "sample. These are counts, not a rate: the sample is too small to quote a "
                   "percentage from, so cite the numbers as numbers." % len(records))

    query = (ticket_type or "").strip().lower()
    if not query or query == "all":
        return {"scope": "all ticket types", "sample_note": sample_note,
                "by_ticket_type": [_reopen_row(label, [r for r in records
                                                       if r.get("intent_label") == label])
                                   for label in labels],
                "overall": _reopen_row("all", records)}

    matched = [r for r in records if r.get("intent_label", "").lower() == query]
    if matched:
        # An exact match can only be one type, so the label is whatever it matched.
        label = matched[0].get("intent_label", ticket_type)
    else:
        # Fixed: a substring can span types where an exact match cannot.
        # "compensation" hits both compensation_hotel_request and
        # compensation_goodwill, and the merged row carried both counts under
        # whichever label came first. Name the candidates instead.
        candidates = sorted({r.get("intent_label", "") for r in records
                             if query in r.get("intent_label", "").lower()})
        if len(candidates) > 1:
            return {"error": "%r matches more than one ticket type in this sample, and "
                             "their counts cannot be reported as one type. Call again "
                             "with whichever of these this contact actually is."
                             % ticket_type,
                    "ticket_types_matched": candidates,
                    "sample_note": sample_note}
        label = candidates[0] if candidates else ""
        matched = [r for r in records if r.get("intent_label", "") == label] if label else []

    if not matched:
        return {"error": "No ticket type matches %r in this sample." % ticket_type,
                "ticket_types_available": labels}

    row = _reopen_row(label, matched)
    row["sample_note"] = sample_note
    return row


# -- the schemas Claude is offered, and the functions behind them -------------
EXTRA_TOOLS: List[Dict[str, Any]] = [   # ✏️ Build 2, step 2.1: schemas for the tools you add
    {
        "name": "current_time",
        "description": (
            "Today's date and the current local time at the Larkspur care desk. Takes "
            "no arguments.\n"
            "When: step 1, before lookup_booking, whenever the customer uses a word "
            "that is relative to the present moment — today, tonight, tomorrow, this "
            "morning, still, yet, by now. Skip it when every date in play is already "
            "absolute, because it costs a round trip most contacts do not need.\n"
            "Returns: the full timestamp, and the date on its own.\n"
            "Rules: this is the only source of today's date. Nothing on the booking "
            "says which of its dates is today.\n"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": [],
                         "additionalProperties": False},
    },
]

LOCAL_TOOLS: Dict[str, Any] = {         # ✏️ Build 2, step 2.1: the functions behind them
    # next_available_day and fare_rules moved out at 2.2: the MCP server owns
    # those names now, and a name can only have one owner.
    "current_time": current_time,               # written in this file, above
}
