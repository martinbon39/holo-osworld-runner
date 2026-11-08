"""Feci Guard, importable entry point and the ONLY place of the accept/reject rule (used by run_holo_guard, the live
duel page and verif-study).

    import sys; sys.path.insert(0, "<repo>/holo-neurochir/feci_guard"); import feci_guard
    r = feci_guard.check(instruction, screenshot_png_bytes, answer, history)    # synchronous, < 60 s, never raises
    r == {"verdict": "accept" | "reject",
          "kind": "complete" | "incomplete" | "need_check" | "no_verdict" | "inconsistent",
          "requirements": [{"text", "ok", "status": "yes"|"no"|"cannot_tell", "evidence"}],
          "feedback": "<text to return to the agent when rejected, else ''>",
          "detail": <raw verifier output: latency_s, model, backend, mode, error, cost_usd, ...>}
Rule: reject on INCOMPLETE with at least one requirement "no", or (active mode) on NEED_CHECK with at least one
"cannot_tell". COMPLETE, no verdict (timeout, error, bad JSON) or a verdict its own statuses contradict -> accept.
ok is True only for "yes"; show "cannot_tell" as "?" from status. answer and history are accepted for the interface
but not sent to the verifier, which judges the task on the screen alone (PREREG.md). Backend and mode: see verifier.py
(GUARD_BACKEND, GUARD_BASE_URL, GUARD_MODEL, GUARD_API_KEY_ENV, GUARD_MODE). The caller owns the episode policy:
do not check answers that declare the task infeasible, at most 2 rejects per episode (run_holo_guard.GuardedAgent).
"""
from __future__ import annotations

import hashlib
import os
import tempfile

import verifier

VERIFIER_SHA = hashlib.sha256(open(verifier.__file__, "rb").read()).hexdigest()[:16]
NEEDS = {"INCOMPLETE": ("no", "incomplete"), "NEED_CHECK": ("cannot_tell", "need_check")}


def feedback(kind: str, v: dict) -> str:
    if kind == "incomplete":
        return (f"Verifier: requirement '{v['missing_requirement']}' is not satisfied on screen: {v['evidence']}. "
                f"{v['next_action']} Continue the task.").replace("..", ".")
    return (f"Verifier: cannot confirm '{v['missing_requirement']}' from the screen ({v['evidence']}). Before "
            f"answering again, make it visible without changing anything: {v['next_action']}").replace("..", ".")


def check(instruction: str, screenshot_png: bytes | None, answer: str = "", history: list[str] | None = None,
          mode: str | None = None, model: str | None = None) -> dict:
    v = {"ok": False, "verdict": None, "requirements": [], "error": "no screenshot", "latency_s": None}
    if screenshot_png:
        with tempfile.TemporaryDirectory(prefix="feci_png_") as d:
            path = os.path.join(d, "screen.png")
            with open(path, "wb") as f:
                f.write(screenshot_png)
            try:
                v = verifier.verify(instruction, path, model=model, mode=mode)
            except Exception as e:  # noqa: BLE001 - a broken guard must never block an answer
                v = {"ok": False, "verdict": None, "requirements": [], "error": repr(e)[:200], "latency_s": None}
    v["verifier_sha"] = VERIFIER_SHA
    statuses = {r.get("status") for r in v.get("requirements", [])}
    kind = {"COMPLETE": "complete", None: "no_verdict"}.get(v.get("verdict"))
    if kind is None:
        need, k = NEEDS[v["verdict"]]
        kind = k if need in statuses else "inconsistent"
    reject = kind in ("incomplete", "need_check")
    return {"verdict": "reject" if reject else "accept", "kind": kind,
            "requirements": [{"text": r.get("requirement", ""), "ok": r.get("status") == "yes",
                              "status": r.get("status"), "evidence": r.get("evidence", "")}
                             for r in v.get("requirements", [])],
            "feedback": feedback(kind, v) if reject else "", "detail": v}
