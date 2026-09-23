#!/usr/bin/env python3
"""Prove prompt caching is still working, because nothing else will tell you.

    python3 support/cache_selftest.py            # structure only, no API key
    python3 support/cache_selftest.py --live     # also runs one real contact

Caching here saves roughly 60-70% of the cost of a contact, and it fails
SILENTLY. Nothing raises. Nothing logs. The agent keeps answering correctly and
the only symptom is the bill, a month later.

It fails silently because the cached region is a byte-exact prefix -- the 12
tool schemas plus the system prompt -- and three unrelated edits break it:

  * anything volatile moved back to the FRONT of the system prompt. That is
    what runtime_preamble() used to do, a clock reading to the second, and it
    held the hit rate at 0% while looking entirely reasonable.
  * the MCP server reordering its tools or editing a description. Those schemas
    are inside the cached prefix and they are served by a SEPARATE program
    (support/mcp_server.py), so a redeploy nobody here reviews can do it.
  * the tool list shrinking below the model's minimum cacheable prefix.

Every line prints PASS or FAIL and the exit code is 0 only when all of them
pass. Run it after touching agent.py, support/data.py or the MCP server.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXERCISE_ROOT = HERE.parent
if str(EXERCISE_ROOT) not in sys.path:
    sys.path.insert(0, str(EXERCISE_ROOT))

MIN_CACHEABLE_TOKENS = 1024          # claude-sonnet-5's floor; Haiku's is 2048
PASSES = 0
FAILURES = 0


def check(ok: bool, label: str, detail: str = "") -> bool:
    global PASSES, FAILURES
    if ok:
        PASSES += 1
        print("PASS  %s%s" % (label, ("  (%s)" % detail) if detail else ""))
    else:
        FAILURES += 1
        print("FAIL  %s%s" % (label, ("  (%s)" % detail) if detail else ""))
    return ok


def structural_checks() -> None:
    import agent
    from support import SYSTEM_PROMPT

    blocks = agent.system_blocks()

    check(isinstance(blocks, list) and len(blocks) >= 1,
          "system is a list of blocks",
          "%d block(s); a bare string has nowhere to hang cache_control" % len(blocks))

    check("cache_control" in blocks[0],
          "the breakpoint is on the FIRST block",
          "marks the end of the static prefix")

    # The whole bug this file exists to catch. The clock used to live here and
    # held the hit rate at 0%; it is the current_time tool now, so NO block may
    # carry it. Two calls a second apart must be byte-identical.
    volatile = "Current time:"
    check(not any(volatile in b.get("text", "") for b in blocks),
          "no clock anywhere in the system prompt",
          "it belongs in the current_time tool, not the prefix")

    import time as _t
    first = json.dumps(agent.system_blocks())
    _t.sleep(1.1)
    check(first == json.dumps(agent.system_blocks()),
          "system prompt is byte-identical one second later",
          "anything that differs here cannot be cached")

    check("current_time" in [t["name"] for t in agent.tool_list()],
          "the clock is reachable as a tool",
          "the model can still find out what time it is")

    # Byte-stability: same input, same bytes, every call.
    a, b, c = (json.dumps(agent.tool_list()) for _ in range(3))
    check(a == b == c, "tool_list() is byte-identical across calls",
          "%d tools, order fixed" % len(agent.tool_list()))

    static_chars = len(a) + len(SYSTEM_PROMPT) + len(agent.TONE_ADDENDUM)
    approx = static_chars // 4
    check(approx >= MIN_CACHEABLE_TOKENS,
          "cached prefix clears the minimum",
          "~%d tokens vs floor of %d" % (approx, MIN_CACHEABLE_TOKENS))


def live_check() -> None:
    """One real contact. The only check that proves the cache actually HIT."""
    import agent
    from support import new_session

    print("\n  running one live contact (needs an API key)...")
    tracer_holder = {}
    real_new_session = new_session

    def spy():
        client, tracer = real_new_session()
        tracer_holder["tracer"] = tracer
        return client, tracer

    agent.new_session = spy
    try:
        agent.run_agent("K7PQ2M", "Marchetti", "My flight was cancelled, what are my options?")
    finally:
        agent.new_session = real_new_session

    tracer = tracer_holder.get("tracer")
    if not check(tracer is not None, "captured a trace"):
        return
    turns = getattr(tracer, "turns", [])
    reads = [t.get("cache_read", 0) for t in turns]
    check(len(turns) >= 2, "contact ran more than one turn", "%d turns" % len(turns))
    check(any(r > 0 for r in reads),
          "the cache was READ on at least one turn",
          "reads per turn: %s" % reads)
    check(all(r > 0 for r in reads[1:]) if len(reads) > 1 else True,
          "every turn after the first read the cache",
          "a zero here means the prefix moved mid-conversation")

    # The conversation breakpoint only pays if the region GROWS turn on turn.
    # Flat reads mean the messages are being written and never read back, which
    # is what happens the moment anything volatile sits ahead of them -- e.g. if
    # run_agent() goes back to calling runtime_preamble() once per turn instead
    # of once per contact. That costs more than not caching them at all.
    check(len(reads) < 2 or reads[-1] > reads[0],
          "the cached region GREW across the contact",
          "%d -> %d; flat means the conversation is written but never read"
          % (reads[0], reads[-1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true",
                    help="also run one real contact and assert the cache was read")
    args = ap.parse_args()

    print("Prompt cache selftest\n" + "-" * 48)
    structural_checks()
    if args.live:
        live_check()
    else:
        print("\n  (structure only. --live proves the cache actually hits.)")

    print("-" * 48)
    print("%d passed, %d failed" % (PASSES, FAILURES))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
