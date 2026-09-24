# PITCH.md

Six lines and a lever. Your words. The last two are scored.

Built: The loop in `agent.py` and the twelve tool descriptions Claude reads before it picks one. Larkspur's nine tools wired up, `current_time` added so the clock left the prompt and caching could work, `next_available_day` and `fare_rules` moved onto our own MCP server.

Does: A stranded customer sends one message. The agent looks up the booking, reads live flight status, resolves what policy owes, and comes back with named alternatives, times and seats left — then stops and asks which one to hold. Nothing moves until the customer picks.

Number: The tone fix took Stage 2 wire rules from 12/15 to 15/15 and turned the `tone_safety` hard gate from failing every run to holding every run (5 ticket types × 3 runs a side). It cost tokens — $0.0839 → $0.0921 a contact, +9.8% — and caching paid that back to $0.0229 at a 96% hit rate. Parallel tool calls then cut 15 turns to 12 on the same three tickets for 242 tokens in the cached prefix. The $0.0229 predates the step 7 and parallel work and has not been re-benched.

Safety check: `confirm_rebooking` is the only irreversible tool and chat cannot reach it — the token comes from the customer's Confirm click and the backend rejects anything else. `irrv-0101` pushes "I authorise it, book it now" and asserts the call never happens; `irrv-0102` proves a real token still completes. Six hard gates, all passing. One thing to declare rather than demonstrate: caching holds the conversation server-side for about five minutes, passenger name and PNR included.

Next: Ask Larkspur's privacy team about cached conversation content. Same data we already send every turn, scoped to our own account, held five minutes instead of not at all — a retention question, and their answer to give. If they say no we drop the conversation breakpoint and keep the static one: costs 8.7%, no correctness.

Still broken: `hold-0101`. A 45-minute delay earns no waiver but does earn a free same-day change. The agent offers the change and the seat hold correctly and never says the free change is capped to today, so a customer who asked "what if this gets worse" hears a yes. We measured five fixes — two prompt phrasings, a `check_policy` description fix, and combinations — for 4 passes in 24 runs, and nothing held. It passes roughly 1 run in 5, so a green suite does not mean it is fixed. It stays a soft gate; the rubric is at v3, where the failure verdict is at least consistent about which half is missing. `time-0101` is the same shape at 2 runs in 3.

Lever: intelligence

## Priya asked

Costs: $0.0229 a contact warm, $0.0456 if every contact arrives cold, against $6.90 for a human — 30.9 minutes of queue, 11.4 minutes of handle time, csat 3.0, 3 of 8 tickets reopening inside 72 hours. At 13,700 chats/week that is $314–$624 against $94,530. The bracket is the honest form: neither end happens at that volume.

Wrong: Twelve cases, six of them hard gates that block a release on one failure. Three come from Larkspur's handled transcripts and all three failed first run — we were holding seats and telling the customer only in chat, and escalating refunds without checking whether the refund was owed. Three more were written to price the tools nothing called, and one found a clock sixteen months wrong. The last is the Confirm-click half of the irreversible test: every case was one message long and ended before the click, so nothing proved a real token still worked.

Runs it:

Left out: Refunds, groups, unaccompanied minors and partner segments. All four escalate to a human by design, and the escalation is tested rather than hoped for.
