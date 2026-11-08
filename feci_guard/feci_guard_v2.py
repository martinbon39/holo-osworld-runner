"""Feci Guard v2 entry point: the variant selected in v2/PROTOCOL.md ("ab": Claude Opus + history = the 2 screens
before the answer + the agent's action list, non-strict prompt). Same return shape and the same accept/reject rule as
feci_guard.check (v1, frozen), whose rule constants it reuses.

    check(instruction, screenshot_png, history_pngs=[...], actions=[...]) -> {"verdict": accept|reject, "kind", ...}
Backend: GUARD_V2_BASE_URL set -> the relay guard_server_v2.py (OpenAI-shaped request; images as data URLs; the
instruction and actions in a FECI_V2 JSON text part; the relay runs verifier_v2.verify_v2 exactly). Unset -> local
`claude -p` through verifier_v2. history_from_episode(dir) rebuilds history the way v2/run_v2.py did offline.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile

import feci_guard as v1guard
import verifier_v2

MODEL = "opus"
CLIENT_TIMEOUT_S = 150
SERVER_TIMEOUT_S = 120


def history_from_episode(episode_dir: str, n_prev: int = 2) -> tuple[list[str], list[str]]:
    """Last n_prev step screenshots and the tool calls so far (answers excluded: they are the agent's claims)."""
    p = os.path.join(episode_dir, "traj.jsonl")
    steps = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []
    steps = [s for s in steps if s.get("tool_name") != "answer"]
    imgs = [os.path.join(episode_dir, s["screenshot_file"]) for s in steps if s.get("screenshot_file")][-n_prev:]
    acts = [f"{s['tool_name']}({json.dumps({k: v for k, v in (s.get('tool_call') or {}).items() if k != 'tool_name'}, ensure_ascii=False)[:160]})"
            for s in steps]
    return imgs, acts


def _relay(instruction, path, hist_paths, actions):
    from openai import OpenAI
    url = lambda p: "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()
    client = OpenAI(base_url=os.environ["GUARD_V2_BASE_URL"], api_key="EMPTY", timeout=CLIENT_TIMEOUT_S, max_retries=0)
    content = [{"type": "text", "text": "FECI_V2 " + json.dumps({"instruction": instruction, "actions": actions})}]
    content += [{"type": "image_url", "image_url": {"url": url(p)}} for p in hist_paths + [path]]
    r = client.chat.completions.create(model="feci-guard-v2", messages=[{"role": "user", "content": content}])
    return json.loads(r.choices[0].message.content)


def check(instruction: str, screenshot_png: bytes | None, history_pngs: list[str] | None = None,
          actions: list[str] | None = None) -> dict:
    hist, actions = list(history_pngs or []), list(actions or [])
    v = {"ok": False, "verdict": None, "requirements": [], "error": "no screenshot", "latency_s": None}
    if screenshot_png:
        with tempfile.TemporaryDirectory(prefix="feci2_png_") as d:
            path = os.path.join(d, "screen.png")
            with open(path, "wb") as f:
                f.write(screenshot_png)
            try:
                v = (_relay(instruction, path, hist, actions) if os.environ.get("GUARD_V2_BASE_URL")
                     else verifier_v2.verify_v2(instruction, path, hist, actions, model=MODEL, timeout=SERVER_TIMEOUT_S))
            except Exception as e:  # noqa: BLE001 - a broken guard must never block an answer
                v = {"ok": False, "verdict": None, "requirements": [], "error": repr(e)[:200], "latency_s": None}
    v["guard_version"] = "v2-ab"
    statuses = {r.get("status") for r in v.get("requirements", [])}
    kind = {"COMPLETE": "complete", None: "no_verdict"}.get(v.get("verdict"))
    if kind is None:
        need, k = v1guard.NEEDS.get(v["verdict"], (None, "inconsistent"))
        kind = k if need in statuses else "inconsistent"
    reject = kind in ("incomplete", "need_check")
    return {"verdict": "reject" if reject else "accept", "kind": kind,
            "requirements": [{"text": r.get("requirement", ""), "ok": r.get("status") == "yes",
                              "status": r.get("status"), "evidence": r.get("evidence", "")}
                             for r in v.get("requirements", [])],
            "feedback": v1guard.feedback(kind, v) if reject else "", "detail": v}
