"""run_holo + Feci Guard + escalation: when the Guard refuses an answer, the rest of the episode is played by a RESCUE
model (e.g. Holo4-27B), with the full history and the Guard feedback. The Guard stays active (2 refusals max).
Imports the frozen run_holo_guard and only swaps its GuardedAgent for RescueGuardedAgent; same arguments as
run_holo_guard.py (--guard must be on).

Environment (keys are read only from the variables named here, never from the command line):
  RESCUE_BASE_URL       OpenAI-compatible endpoint of the rescue model (e.g. https://…modal.run/v1)
  RESCUE_MODEL          served model name (e.g. Holo4-27B)
  RESCUE_API_KEY_ENV    NAME of the variable holding its key (sent as Bearer)
  Guard judge: GUARD_BACKEND / GUARD_BASE_URL / GUARD_MODEL / GUARD_API_KEY_ENV, see verifier.py.
The rescue model is called through the frozen HoloComputerAgent._call_model (same prompt, schema, sampling).
meta.json "feci_guard" gains "rescue": {model, escalated_at_step, calls}.
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_holo_guard as RG  # noqa: E402
from openai import OpenAI  # noqa: E402

log = logging.getLogger("holo_repro.rescue")


class RescueGuardedAgent(RG.GuardedAgent):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.rescue_model = os.environ["RESCUE_MODEL"]
        self.rescue_client = OpenAI(base_url=os.environ["RESCUE_BASE_URL"],
                                    api_key=os.environ[os.environ["RESCUE_API_KEY_ENV"]], timeout=300)
        self.escalated_at = None
        self.rescue_calls = 0

    def _check(self, step_idx: int, answer: str) -> dict:
        rec = super()._check(step_idx, answer)
        if rec["decision"] == "refused" and self.escalated_at is None:
            self.escalated_at = step_idx + 1
            self.client, self.model = self.rescue_client, self.rescue_model
            log.info("[rescue] step %d: Guard refused, the episode continues with %s", step_idx + 1, self.model)
            with open(os.path.join(self.guard_dir, "guard.md"), "a", encoding="utf-8") as f:
                f.write(f"**Escalation:** from step {step_idx + 2} the agent is {self.model}.\n\n")
        return rec

    def _call_model(self, messages):
        if self.escalated_at is not None:
            self.rescue_calls += 1
        return super()._call_model(messages)

    def guard_summary(self) -> dict:
        return {**super().guard_summary(),
                "rescue": {"model": self.rescue_model, "escalated_at_step": self.escalated_at, "calls": self.rescue_calls}}


RG.GuardedAgent = RescueGuardedAgent  # run_holo_guard.run_one builds GuardedAgent by global name (spawn workers too)

if __name__ == "__main__":
    missing = [v for v in ("RESCUE_BASE_URL", "RESCUE_MODEL", "RESCUE_API_KEY_ENV") if not os.environ.get(v)]
    if missing or not os.environ.get(os.environ.get("RESCUE_API_KEY_ENV", ""), ""):
        sys.exit(f"rescue model not configured: {missing or 'key variable empty'}")
    if "--guard" in sys.argv and sys.argv[sys.argv.index("--guard") + 1] != "on":
        sys.exit("run_holo_guard_rescue needs --guard on")
    RG.main()
