"""run_holo + Feci Guard v2 (opus + history). Imports the frozen run_holo_guard and swaps its GuardedAgent for
GuardedAgentV2, whose check sends the 2 screens before the answer and the action list (read from the episode's own
traj.jsonl, as offline). Same arguments as run_holo_guard.py (--guard on). Judge: local `claude -p` (default) or the
v2 relay with GUARD_V2_BASE_URL=http://127.0.0.1:9912/v1. Same episode policy as v1: infeasible answers unchecked,
at most 2 refusals, fail-open.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_holo_guard as RG  # noqa: E402
import feci_guard_v2  # noqa: E402
import verifier  # noqa: E402


class GuardedAgentV2(RG.GuardedAgent):
    def _check(self, step_idx: int, answer: str) -> dict:
        refusals = sum(1 for g in self.guard_log if g["decision"] == "refused")
        rec = {"step": step_idx + 1, "answer": answer, "refusals_before": refusals, "guard_version": "v2-ab"}
        if RG._INFEASIBLE_RE.search(answer or ""):
            rec.update(decision="passed_infeasible")
        elif refusals >= self.max_refusals:
            rec.update(decision="passed_cap")
        else:
            try:
                png = self.env.env.controller.get_screenshot()
            except Exception:  # noqa: BLE001
                png = None
            shot = f"guard_step_{step_idx + 1}.png"
            if png:
                with open(os.path.join(self.guard_dir, shot), "wb") as f:
                    f.write(png)
            hist, acts = feci_guard_v2.history_from_episode(self.guard_dir)
            r = feci_guard_v2.check(self.instruction, png, hist, acts)
            rec.update(verifier=r["detail"], kind=r["kind"], feedback=r["feedback"], screenshot=shot if png else None,
                       history=[os.path.basename(h) for h in hist],
                       decision="refused" if r["verdict"] == "reject" else f"passed_{r['kind']}")
        self.guard_log.append(rec)
        with open(os.path.join(self.guard_dir, "guard.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        with open(os.path.join(self.guard_dir, "guard.md"), "a", encoding="utf-8") as f:
            f.write(f"## step {rec['step']} answer -> {rec['decision'].upper()} (guard v2)\n> {answer}\n\n")
            if "verifier" in rec:
                f.write("```\n" + verifier.render(rec["verifier"]) + "\n```\n")
                if rec["decision"] == "refused":
                    f.write(f"Feedback to agent: {rec['feedback']}\n")
            f.write("\n")
        RG.logger.info("[guard v2] step %d %s", rec["step"], rec["decision"])
        return rec

    def guard_summary(self) -> dict:
        return {**super().guard_summary(), "guard_version": "v2-ab", "guard_model": feci_guard_v2.MODEL}


RG.GuardedAgent = GuardedAgentV2  # run_holo_guard.run_one builds GuardedAgent by global name (spawn workers too)

if __name__ == "__main__":
    RG.main()
