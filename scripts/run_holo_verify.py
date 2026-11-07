"""run_holo.py with one extra system-prompt variant, 'v2_verify' (prompt baseline, AxBench-style): v2 plus one bullet
at the end of its 'Finishing' section. The shared harness files are not modified: the variant is registered in
holo_agent.SYSTEM_PROMPTS at import time, and run_holo's spawn workers re-import this module as __mp_main__, so they
see it too. Usage (from the OSWorld root, like run_holo.py): python <this file> --prompt v2_verify <run_holo args>
"""
import os, sys

HOLO_REPRO = os.path.expanduser("~/osw/rtg/Env/OSWorld/holo_repro")
sys.path.insert(0, HOLO_REPRO)
sys.path.insert(0, os.path.dirname(HOLO_REPRO))
from holo_agent import SYSTEM_PROMPTS  # noqa: E402

VERIFY = ("Before calling answer, look at the current screenshot and check that every requirement of the task is "
          "visibly satisfied; if anything is missing or unconfirmed, continue working instead of answering.")
TAIL = "\n\n{schema_block}"
if "v2_verify" not in SYSTEM_PROMPTS:
    base = SYSTEM_PROMPTS["v2"]
    assert base.count(TAIL) == 1 and base.endswith(TAIL) and "\nFinishing:\n" in base, "v2 prompt layout changed"
    SYSTEM_PROMPTS["v2_verify"] = base[: -len(TAIL)] + f"\n- {VERIFY}" + TAIL

import run_holo  # noqa: E402

if __name__ == "__main__":
    run_holo.main()
