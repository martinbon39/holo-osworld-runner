"""Feci Guard verifier v2 (v1 = verifier.py, frozen: the online S0 run uses it). Same schema, same CLI call; options:
  history   the last screens before the answer (oldest first) + the list of the agent's actions (tool calls only,
            never its notes or claims), read as extra files
  model     any `claude -p` model alias (sonnet, opus)
  unblock   (online option, not measured offline) next_action must not repeat a failed action and should prefer a
            keyboard fallback; it only changes the feedback text the agent receives
  strict    "file evidence" prompt: a requirement whose change is not visible (formatting detail, exact value, saved
            state) is "yes" only with direct evidence at file/structure level on screen; otherwise "cannot_tell", and
            a decisive "cannot_tell" makes the verdict INCOMPLETE instead of COMPLETE.
verify_v2(instruction, image_path, history_images=(), actions=(), model="sonnet", strict=False) -> same dict as v1.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time

import verifier as v1

HISTORY_BLOCK = """
Before that final screen, the agent saw these screens (oldest first): {history_names}. Read them too with the Read tool;
they show how the agent got there, but judge the task on the FINAL screen.
The agent's actions so far (tool calls, oldest first):
{actions}
"""

STRICT_STEPS = """3. VERDICT: "INCOMPLETE" if at least one requirement is "no" (visibly not satisfied). Many changes are not
   visible as such (character formatting, the exact extent of a selection, a cell value, a setting, saved state):
   mark such a requirement "yes" only with direct evidence of the exact final state on screen (e.g. the format
   toolbar state for the selected text, the cell content in the formula bar, the setting shown in its dialog, no
   unsaved marker). Approximate or partial evidence is "no" if it shows a defect, otherwise "cannot_tell".
   If a requirement that decides the task is "cannot_tell", the verdict is "INCOMPLETE" (the agent must show it),
   not "COMPLETE". Requirements that are incidental (not what the task is about) never make it INCOMPLETE.
   "COMPLETE" only if every deciding requirement is "yes".
4. If INCOMPLETE: missing_requirement = the single most important requirement that is not satisfied or not shown,
   evidence = what on the screen shows it (or why the screen cannot show it), next_action = what the agent should do
   next (one short concrete instruction: fix it, or make it visible without changing anything).
   If COMPLETE: those three fields are empty strings.
"""


UNBLOCK_HINT = ("   next_action must not repeat an action the agent already tried that did not work (see its actions); "
                "prefer a keyboard fallback (a shortcut, or the menu path) to clicking again.\n")


def build_prompt(strict: bool, history_names: list[str], actions: list[str], unblock: bool = False) -> str:
    p = v1.PROMPT.replace(v1.PASSIVE_STEPS, STRICT_STEPS) if strict else v1.PROMPT
    if unblock:
        p = p.replace("Answer only with the JSON object required by the schema.",
                      UNBLOCK_HINT + "Answer only with the JSON object required by the schema.")
    if history_names:
        block = HISTORY_BLOCK.format(history_names=", ".join(history_names),
                                     actions="\n".join(f"  {i + 1}. {a}" for i, a in enumerate(actions)) or "  (none)")
        p = p.replace("at the moment the agent declares the task done. Then:",
                      "at the moment the agent declares the task done." + block.replace("{", "{{").replace("}", "}}") + "Then:")
    return p


def verify_v2(instruction: str, image_path: str, history_images=(), actions=(), model: str = "sonnet",
              strict: bool = False, timeout: float = v1.TIMEOUT_S, unblock: bool = False) -> dict:
    t0 = time.time()
    out = {"ok": False, "verdict": None, "requirements": [], "missing_requirement": "", "evidence": "",
           "next_action": "", "model": model, "backend": "claude", "mode": "v2", "strict": strict,
           "history": len(history_images), "unblock": unblock, "error": None, "cost_usd": None}
    with tempfile.TemporaryDirectory(prefix="feci2_") as work:
        name = "screen" + os.path.splitext(image_path)[1].lower()
        shutil.copy(image_path, os.path.join(work, name))
        hist = []
        for i, h in enumerate(history_images):
            hn = f"before_{i + 1}" + os.path.splitext(h)[1].lower()
            shutil.copy(h, os.path.join(work, hn))
            hist.append(hn)
        prompt = build_prompt(strict, hist, list(actions), unblock).format(instruction=instruction, image_name=name)
        cmd = [v1.CLAUDE, "-p", prompt, "--model", model, "--output-format", "json",
               "--json-schema", json.dumps(v1.SCHEMA), "--tools", "Read", "--allowedTools", "Read",
               "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"]
        env = {k: v for k, v in os.environ.items() if not k.startswith("ARGOS")}
        try:
            p = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=timeout, env=env,
                               stdin=subprocess.DEVNULL)
            obj, out["cost_usd"], out["error"] = v1._parse(p.stdout)
            if obj is None and p.returncode != 0:
                out["error"] = f"exit {p.returncode}: {(p.stderr or p.stdout)[-200:]}"
        except subprocess.TimeoutExpired:
            obj, out["error"] = None, f"timeout after {timeout:.0f}s"
    if obj is not None:
        out.update({k: obj.get(k, "") for k in ("requirements", "verdict", "missing_requirement", "evidence",
                                                 "next_action")})
        out["ok"] = True
    out["latency_s"] = round(time.time() - t0, 1)
    return out
