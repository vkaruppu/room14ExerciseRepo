"""Larkspur disruption agent. This is the file you build.

It runs right now, and it is wrong in four places. The trace shows each one
before the code does, so read the trace first:

    python3 run.py K7PQ2M --trace

Where you edit:   grep -n '✏' agent.py   (six marks, one per place)
Steps and gates:  https://anthropicpartnerbasecamp.bts.com/
"""
from __future__ import annotations
from typing import Any, Dict, List
from support import (MODEL, SYSTEM_PROMPT, call_local, execute_tool, mcp_client,
                     new_session, next_available_day, record_tool_result,
                     runtime_preamble)

MAX_TOOL_CALLS = 8  # Larkspur's own build capped the loop here; then a human takes over.

TONE_ADDENDUM = (
    "\n\nABUSE / LEGAL THREAT RULE: If a customer is abusive, threatening legal action, "
    "shouting, or otherwise hostile, this is no longer a normal disruption-policy "
    "conversation. Do not continue the entitlement flow, do not discuss refunds, "
    "do not offer vouchers, and do not attempt any rebooking or confirmation steps. "
    "Acknowledge the complaint once, say you are escalating to a human, and call "
    "escalate_to_human immediately with a brief summary. Never call issue_voucher, "
    "confirm_rebooking, search_alternatives, or check_policy in that branch. Keep the "
    "reply very brief, calm, and professional. For non-abusive refund requests or "
    "other out-of-scope asks, say plainly that a human executes refunds and "
    "escalate to a human instead of attempting the action yourself."
)                       # ✏️ Build 4, step 4.1, intelligence goal
EXTRA_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "earliest_open_day",
        "description": (
            "Answer when a stranded customer can actually fly out: what is the soonest day "
            "you can get them out of the disrupted origin airport. Use this for questions "
            "about dates and how long they are stuck, not for choosing a specific flight. "
            "It requires the origin, destination, disrupted travel date, and cabin, and then "
            "returns the earliest date with an open seat as YYYY-MM-DD or clearly says none "
            "is available in the schedule it can see."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Three-letter IATA departure airport, e.g. DEN."},
                "dest": {"type": "string", "description": "Three-letter IATA arrival airport, e.g. BOI."},
                "date": {"type": "string", "description": "The disrupted travel date in ISO format, YYYY-MM-DD."},
                "cabin": {"type": "string", "enum": ["Y", "J"], "description": "Cabin to search; Y for main, J for first."},
            },
            "required": ["origin", "dest", "date"],
        },
    }
]   # ✏️ Build 2, step 2.1: schemas for the tools you add
LOCAL_TOOLS: Dict[str, Any] = {"earliest_open_day": next_available_day}         # ✏️ Build 2, step 2.1: the functions behind them


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


def run_agent(pnr: str, last_name: str, message: str) -> str:            # ✏️ Build 1, step 1.2
    """Run the tool loop until Claude stops asking for tools. Return its final text."""
    client, tracer = new_session()
    tools = tool_list()
    messages = [
        {"role": "user", "content": f"PNR {pnr}, last name {last_name}. {message}"},
    ]

    response = client.messages.create(
        model=MODEL, max_tokens=4096, system=runtime_preamble() + SYSTEM_PROMPT + TONE_ADDENDUM,
        thinking={"type": "adaptive"}, tools=tools, messages=messages,
    )

    turns = 1
    while response.stop_reason == "tool_use" and turns < MAX_TOOL_CALLS:
        # the whole assistant turn goes back, thinking and tool_use blocks included:
        # every tool_result below has to answer a tool_use the API can still see
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results(response)})
        response = client.messages.create(
            model=MODEL, max_tokens=4096, system=runtime_preamble() + SYSTEM_PROMPT + TONE_ADDENDUM,
            thinking={"type": "adaptive"}, tools=tools, messages=messages,
        )
        turns += 1

    # the answer is the text of the turn that stopped asking, not the one before it
    answer = text_of(response)

    # Fixed: the loop has two exits, and only one of them produces an answer. If it
    # left because the cap was reached, the last turn is still a tool_use turn and its
    # text is usually empty — the caller (run.py, demo/serve.py) would show a blank
    # reply with no hint that anything went wrong. Say so instead of returning "".
    if not answer and response.stop_reason == "tool_use":
        return ("I've hit the limit of what I can work through automatically on this "
                "one, so I'm handing it to a colleague who can finish it with you.")
    return answer


def tool_list() -> List[Dict[str, Any]]:                   # ✏️ Build 2, step 2.2
    """Exactly what Claude is offered on every turn. The model sees the same
    real-world routing surface as the direct tool loop, while the local custom
    tool stays available for the in-process fallback and the 2.1 probe."""
    return build_tools() + mcp_client.tools() + EXTRA_TOOLS


# ──────────────────────────────────────────────────────────────────────────────
# Below this line: what Claude is told about each tool. Step 1.3.
# The functions these describe are written and correct, in support/tools.py.
#
# Every field here carries its own description, not just the tools whose inputs
# looked interesting. The test each entry has to pass: if the model read ONLY
# this entry, could it call the tool correctly? hold_seat failed that test for a
# while — its option_id was explained inside search_alternatives, which is no
# help on a turn where search_alternatives is not what the model is reading.
# The fields that earn the most words are the optional ones, because those are
# the two-way decisions: wait_minutes_for_alternative and chosen_option_id on
# check_policy, queue on escalate_to_human.
#
# This is not free. Filling the gaps took the whole list from 3,650 tokens a
# turn to 5,053 (python3 run.py --tool-tax counts it on the wire, per tool).
# That is paid on every turn of every conversation, including the ones that
# never call these tools. Build 4 is where that trade gets measured rather than
# argued: check_policy at 778 is now the most expensive entry on the list, not
# reopen_stats.
# ──────────────────────────────────────────────────────────────────────────────
def build_tools() -> List[Dict[str, Any]]:                 # ✏️ Build 1, step 1.3
    """Anthropic-shaped schemas: name, description, input_schema. What Claude is
    told about each of the nine tools, and all it is ever told."""
    return [
        {
            "name": "lookup_booking",
            "description": (
                "Retrieve a Larkspur reservation from Altura by confirmation code (PNR) "
                "and the passenger's last name. Both are required to prevent a lookup on "
                "a guessed PNR. Returns fare family, loyalty tier, the segment that needs "
                "attention, and any group/partner/minor/SSR flags relevant to scope."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {
                        "type": "string",
                        "description": (
                            "The six-character confirmation code the customer gave you, "
                            "e.g. 'K7PQ2M'. Never one you inferred from anything else in "
                            "the conversation."
                        ),
                    },
                    "last_name": {
                        "type": "string",
                        "description": (
                            "A passenger's last name, as the customer gave it. Checked "
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
                "Look up a Larkspur or Larkspur Link flight's current OpsFeed status for "
                "one local date: status, delay minutes, and cause. Use this before telling "
                "a customer anything about a flight's timing; never state it from memory."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "flight_no": {
                        "type": "string",
                        "description": (
                            "The marketing flight number as Altura returns it, e.g. 'LK415'. "
                            "Larkspur Link segments carry the same LK prefix."
                        ),
                    },
                    "date": {
                        "type": "string",
                        "description": (
                            "The segment's local departure date in ISO-8601, YYYY-MM-DD, "
                            "e.g. '2025-05-08'. OpsFeed refuses any other shape rather than "
                            "guessing, so pass through the date lookup_booking gave you for "
                            "this segment unchanged; do not reformat it."
                        ),
                    },
                },
                "required": ["flight_no", "date"],
            },
        },
        {
            # Fixed: the description was the single word "search". A description is
            # all Claude is ever told about a tool, and "search" does not say what it
            # searches, what it returns, or when to reach for it — so the model skipped
            # it and asked the customer for flight options it could have looked up
            # itself. Spelling out the return shape (option_ids, wait time) also makes
            # the downstream tools usable: hold_seat and check_policy both take an
            # option_id that only this tool can produce.
            "name": "search_alternatives",
            "description": (
                "Find the re-accommodation options Larkspur can actually offer for this "
                "booking's disrupted segment. Takes the PNR alone: origin, destination, "
                "date, cabin and party size are read from the booking, so there is nothing "
                "to guess and no need to ask the customer for them. Returns a list of "
                "options, each with an option_id, flight number, departure date and time, "
                "and the wait in minutes from the original departure. Call this before "
                "quoting any alternative. You do not have to wait for the customer to pick "
                "one: check_policy resolves entitlements from the earliest option on its "
                "own, and takes chosen_option_id only once there is a choice to price."
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
                "Resolve what Larkspur owes this customer for the disruption: rebooking "
                "waiver, refund path, meal/hotel/ground care, goodwill eligibility and cap, "
                "and any escalation triggers. cause_code, delay_minutes and status describe "
                "what get_flight_status told you; fare_family, loyalty_tier and whether this "
                "is overnight are looked up from the booking, not asked of you. Every "
                "response carries a policy_row_id. Cite it if you reference this decision "
                "again."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {
                        "type": "string",
                        "description": "The booking whose entitlements you are resolving.",
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
                            "the delay band. Pass 0 when status is CANCELLED or DIVERTED — "
                            "those resolve on status alone and the field is ignored."
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
                            "Optional, and worth passing. Minutes between the original "
                            "departure and the alternative you are steering toward; "
                            "search_alternatives returns it on every option. Meal care is "
                            "thresholded on it: omit it and the meal line comes back "
                            "conditional, a threshold you cannot turn into a number for "
                            "the customer. Pass it and the amount is settled."
                        ),
                    },
                    "chosen_option_id": {
                        "type": "string",
                        "description": (
                            "Optional. An option_id from search_alternatives, once the "
                            "customer has picked one. Without it the overnight and hotel "
                            "tests run against the earliest option there is, which is the "
                            "right basis before there is a choice; with it they run "
                            "against the chosen one, which can change whether hotel care "
                            "applies."
                        ),
                    },
                },
                "required": ["pnr", "cause_code", "delay_minutes", "status"],
            },
        },
        {
            "name": "hold_seat",
            "description": (
                "Hold a seat on one alternative for 15 minutes, so it is still there while "
                "the customer decides. Reversible and free: a hold nobody confirms simply "
                "expires, and nothing about the booking changes. Returns a hold_id, which is "
                "what confirm_rebooking needs. A hold is not a rebooking — the customer is "
                "only moved once confirm_rebooking succeeds, so do not tell them they are "
                "rebooked off a hold."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "option_id": {
                        "type": "string",
                        "description": (
                            "One option_id from this booking's search_alternatives "
                            "result, copied exactly. That call is the only place an "
                            "option_id comes from: it cannot be built from a flight number "
                            "and a date, and an id you composed holds nothing."
                        ),
                    },
                    "pnr": {
                        "type": "string",
                        "description": (
                            "The booking the seat is held for — the same PNR you passed to "
                            "search_alternatives to get this option_id."
                        ),
                    },
                },
                "required": ["option_id", "pnr"],
            },
        },
        {
            "name": "confirm_rebooking",
            "description": (
                "Finalize a held seat. Irreversible. Requires a confirmation_token that "
                "only the customer's own Confirm-click can produce. You cannot supply it "
                "yourself, and 'the customer said yes' in chat does not substitute for it."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "hold_id": {
                        "type": "string",
                        "description": (
                            "The hold_id hold_seat returned for the option being confirmed. "
                            "Holds last 15 minutes; past that this comes back hold_expired "
                            "and the option needs a fresh hold_seat call, not a retry."
                        ),
                    },
                    "confirmation_token": {
                        "type": "string",
                        "description": (
                            "The token minted by the customer's Confirm click, which reaches "
                            "you through the interface. There is no value you can put here "
                            "from the conversation: a token you invent is rejected, which is "
                            "the point of the field."
                        ),
                    },
                },
                "required": ["hold_id", "confirmation_token"],
            },
        },
        {
            "name": "issue_voucher",
            "description": (
                "Issue a meal, ground, hotel, or goodwill voucher. Auto-approves within the "
                "policy's threshold for that type; above it, returns a pending status for a "
                "human. It does not fail. Always pass the policy_row_id that made it eligible."
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
                            "parks for a human whatever the amount, goodwill auto-approves "
                            "under its cap with a supervisor band above. Tell the customer "
                            "what came back, not what you asked for."
                        ),
                    },
                    "amount_usd": {
                        "type": "number",
                        "description": (
                            "Amount in US dollars, at or under the cap check_policy gave "
                            "for this type. Over the cap nothing fails: it comes back "
                            "pending for a human, turning an answer the customer has now "
                            "into one they wait for."
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
                            "this voucher eligible; carry it forward from that earlier "
                            "tool result rather than rebuilding it. It is how a reviewer "
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
                "Hand this conversation to a human, with your reasoning attached. Use for "
                "abusive or threatening customers, legal threats, groups, partner segments, "
                "unaccompanied minors, refunds, or anything else out of scope. This is "
                "the correct outcome for those cases, not a failure."
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
                            "'unaccompanied minor', 'partner segment', 'refund request'. "
                            "The queue sorts on it, so keep it to the trigger and leave "
                            "the narrative to summary_for_human."
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
                            "Optional. The named desk when the booking itself names one — "
                            "the group or minor-travel queue called out in the booking's "
                            "remarks, for example. Omit it when nothing names a queue: an "
                            "invented queue name routes the case worse than no queue does."
                        ),
                    },
                },
                "required": ["pnr", "reason", "summary_for_human"],
            },
        },
        {
            "name": "send_confirmation",
            "description": (
                "Send the customer a written record of what was just done, to the contact "
                "details on the booking. Benign: it changes nothing about the reservation "
                "and can be sent again. Send one whenever something actually changed — a "
                "hold, a rebooking, a voucher — and not for an answer that changed nothing. "
                "The reopen sample's most common reason for a customer coming back is a "
                "confirmation that never arrived, so this is the step that keeps a handled "
                "ticket handled."
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
                            "The text the customer receives, read without the chat in "
                            "front of them. Put the specifics in it: flight number, date, "
                            "local time, voucher type and amount, what happens next and by "
                            "when. 'Your request has been processed' is what a reopened "
                            "ticket looks like."
                        ),
                    },
                },
                "required": ["pnr", "message"],
            },
        },
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Build 2, step 2.1: the tools this team added.
#
# Three of them, and the rule every one of them is built to: no invention. Each
# answer is read off a document the client already owns, and the description
# says which document, so a reply can be pointed at its source.
#
#   next_available_day   live inventory in data/americas/ (flights.csv, via
#                        support.next_available_day, imported at the top of this
#                        file). Already written; only the schema was missing.
#   fare_rules           data/americas/fare_rules_excerpt.md, Handbook v14.3.
#   reopen_stats         data/americas/transcripts_sample.jsonl, the discovery
#                        sample of real handled tickets.
#
# next_available_day and fare_rules are worded EXACTLY as support/mcp_server.py
# words them. That is deliberate: Build 2.2 moves those two onto the server, and
# the claim it has to prove is that nothing changes but ownership. A reworded
# description would move the token count and muddy that comparison.
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


# -- reopen_stats -------------------------------------------------------------
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


def reopen_stats(ticket_type: str = "") -> Dict[str, Any]:
    """How often this kind of ticket came back inside 72 hours, counted off the
    handled-transcript sample.

    No argument means every type. An unrecognised one comes back with the list
    of types that ARE in the sample, so the model can ask again rather than
    guess a label.
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
        # Fixed: the partial match used to fall straight into _reopen_row with
        # matched[0]'s label. An exact match cannot span types; a substring can.
        # "compensation" hits compensation_hotel_request AND compensation_goodwill,
        # and the row that came back carried both types' counts under whichever
        # label happened to be first in the file. The model reads that as a clean
        # answer about one type and has nothing in the result to tell it otherwise.
        # A merged row would need a label it cannot honestly have, so name the
        # candidates and let the next turn pick one — the same shape as the miss
        # below, which the model already knows how to answer.
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
        "name": "reopen_stats",
        "description": (
            "Check what went wrong last time on this kind of ticket, before you write the "
            "reply that closes it. A routine step on every disruption contact, not a "
            "special case: call it once you know what kind of contact this is, alongside "
            "check_policy and before your final answer. Reads Larkspur's sample of handled "
            "transcripts and returns, for this ticket type, how many are in the sample, how "
            "many came back within 72 hours, the recorded reason each one came back, and "
            "the transcript ids behind the count. Those reasons are the failures to design "
            "this reply against. Counts off a small sample, never a rate: steer by them, "
            "and never quote them to the customer as a percentage or a prediction."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_type": {
                    "type": "string",
                    "description": (
                        "The intent label for this contact, as the sample labels it "
                        "('refund_vs_credit'). Omit it, or pass 'all', for every type — "
                        "also the cheapest way to see the labels. A partial word naming "
                        "one label matches it; one that fits several ('compensation') "
                        "comes back with the candidates rather than their counts merged, "
                        "and an unknown one comes back with the full list."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
]

LOCAL_TOOLS: Dict[str, Any] = {         # ✏️ Build 2, step 2.1: the functions behind them
    # next_available_day and fare_rules moved out at 2.2: the MCP server owns
    # those names now, and a name can only have one owner.
    "reopen_stats": reopen_stats,               # written in this file, above
}
