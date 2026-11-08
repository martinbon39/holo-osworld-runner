"""Feci Guard verifier: a stronger model checks every requirement of an OSWorld task on one screenshot and returns a
strict JSON verdict. Backends: Claude through the local `claude -p` CLI, or any OpenAI-compatible endpoint.
The decision rule (accept / reject) lives in feci_guard.check, not here.

verify(instruction, image_path, model=None, timeout=55, mode=None) -> dict with keys
  ok           True when the backend answered with a valid verdict, False on timeout / error / invalid JSON
  verdict      "COMPLETE" | "INCOMPLETE" | "NEED_CHECK" (active mode only) | None
  requirements [{"requirement", "status": "yes"|"no"|"cannot_tell", "evidence"}]
  missing_requirement, evidence, next_action   (filled when INCOMPLETE / NEED_CHECK)
  latency_s, model, backend, mode, error, cost_usd
CLI usage (manual test): python verifier.py --task "<instruction>" --image shot.png
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time

CLAUDE = os.environ.get("FECI_CLAUDE", "/home/orbit/.local/bin/claude")
DEFAULT_MODEL = os.environ.get("GUARD_MODEL", "sonnet")
TIMEOUT_S = 55

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["requirements", "verdict", "missing_requirement", "evidence", "next_action"],
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["requirement", "status", "evidence"],
                "properties": {
                    "requirement": {"type": "string"},
                    "status": {"type": "string", "enum": ["yes", "no", "cannot_tell"]},
                    "evidence": {"type": "string"},
                },
            },
        },
        "verdict": {"type": "string", "enum": ["COMPLETE", "INCOMPLETE"]},
        "missing_requirement": {"type": "string"},
        "evidence": {"type": "string"},
        "next_action": {"type": "string"},
    },
}

PROMPT = """You are the external verifier of a computer-use agent working on an Ubuntu desktop.
The agent claims it has finished this task:

TASK: {instruction}

Read the screenshot file {image_name} (in the current directory) with the Read tool. It shows the screen right now,
at the moment the agent declares the task done. Then:
1. List every requirement of the task (each distinct thing that must be true when the task is done: the target
   content or value, the right file/app/location, every element or setting the task names, saved state if the task
   implies it, etc.).
2. For each requirement: is it satisfied ON THIS SCREEN? status "yes", "no" or "cannot_tell", with the concrete
   visual evidence (what you see, where).
3. VERDICT: "INCOMPLETE" if at least one requirement is "no" (visibly not satisfied); otherwise "COMPLETE".
   A requirement you cannot check from this screen is "cannot_tell" and does not by itself make the task INCOMPLETE.
4. If INCOMPLETE: missing_requirement = the single most important requirement that is not satisfied, evidence = what
   on the screen shows it, next_action = what the agent should do next (one short concrete instruction).
   If COMPLETE: those three fields are empty strings.
Answer only with the JSON object required by the schema."""

# Active mode: when the screen cannot show a requirement that decides the task (file content, a saved setting,
# terminal state), the verifier asks the agent to make it visible first (NEED_CHECK) instead of letting it pass.
PASSIVE_STEPS = PROMPT[PROMPT.index("3. VERDICT"):PROMPT.index("Answer only")]
ACTIVE_STEPS = """3. VERDICT: "INCOMPLETE" if at least one requirement is "no" (visibly not satisfied). Otherwise "NEED_CHECK"
   if a requirement that decides the task is "cannot_tell" and the agent could make it visible without changing
   anything (open the saved file, open the settings dialog that holds the value, run a read-only command such as
   `cat file` or `ls -l` in a terminal, scroll to the cell). Otherwise "COMPLETE".
4. If INCOMPLETE: missing_requirement = the single most important requirement that is not satisfied, evidence = what
   on the screen shows it, next_action = what the agent should do next (one short concrete instruction).
   If NEED_CHECK: missing_requirement = the requirement to check, evidence = why this screen cannot show it,
   next_action = the one read-only action that would show it (the agent must not change anything while checking).
   If COMPLETE: those three fields are empty strings.
"""
ACTIVE_PROMPT = PROMPT.replace(PASSIVE_STEPS, ACTIVE_STEPS)
ACTIVE_SCHEMA = json.loads(json.dumps(SCHEMA))
ACTIVE_SCHEMA["properties"]["verdict"]["enum"] = ["COMPLETE", "INCOMPLETE", "NEED_CHECK"]
VERDICTS = {"passive": ("COMPLETE", "INCOMPLETE"), "active": ("COMPLETE", "INCOMPLETE", "NEED_CHECK")}


def _parse(stdout: str, mode: str = "passive") -> tuple[dict | None, float | None, str | None]:
    """The CLI's --output-format json wrapper -> (verdict object, cost, error)."""
    try:
        wrap = json.loads(stdout)
    except json.JSONDecodeError:
        return None, None, "cli output is not JSON"
    if not isinstance(wrap, dict):
        return None, None, "cli output is not a JSON object"
    cost = wrap.get("total_cost_usd")
    if wrap.get("is_error"):
        return None, cost, f"cli error: {str(wrap.get('result'))[:200]}"
    obj = wrap.get("structured_output")
    if obj is None:
        try:
            obj = _json_text(wrap.get("result"))
        except json.JSONDecodeError:
            return None, cost, "result is not JSON"
    err = _validate(obj, mode)
    return (None if err else obj), cost, err


READ_LINE = ("Read the screenshot file {image_name} (in the current directory) with the Read tool. It shows the "
             "screen right now,")
IMAGE_LINE = "The attached image shows the screen right now,"
PROMPTS = {"passive": (PROMPT, SCHEMA), "active": (ACTIVE_PROMPT, ACTIVE_SCHEMA)}


def verify(instruction: str, image_path: str, model: str | None = None, timeout: float = TIMEOUT_S,
           mode: str | None = None) -> dict:
    """Backend from GUARD_BACKEND: "claude" (local CLI) or "openai" (any OpenAI-compatible endpoint with image input:
    GUARD_BASE_URL, GUARD_MODEL, and GUARD_API_KEY_ENV = the NAME of the env var holding the key). Unset: openai when
    GUARD_BASE_URL is set (the GitHub workflow sets only that), else claude. mode: "passive" (default, the frozen
    verifier) or "active" (may answer NEED_CHECK); unset = GUARD_MODE env, else passive."""
    mode = mode or os.environ.get("GUARD_MODE", "passive")
    if os.environ.get("GUARD_BACKEND") == "openai" or (not os.environ.get("GUARD_BACKEND") and os.environ.get("GUARD_BASE_URL")):
        return verify_openai(instruction, image_path, model or DEFAULT_MODEL, timeout, mode)
    return verify_claude(instruction, image_path, model or DEFAULT_MODEL, timeout, mode)


def _validate(obj, mode: str = "passive") -> str | None:
    if not isinstance(obj, dict) or obj.get("verdict") not in VERDICTS[mode] \
            or not isinstance(obj.get("requirements"), list):
        return "verdict object does not match the schema"
    return None


def _json_text(text: str):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    if "{" in text:
        return json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
    return json.loads(text)


def verify_openai(instruction: str, image_path: str, model: str, timeout: float = TIMEOUT_S,
                  mode: str = "passive") -> dict:
    import base64
    from openai import OpenAI
    t0 = time.time()
    out = {"ok": False, "verdict": None, "requirements": [], "missing_requirement": "", "evidence": "",
           "next_action": "", "model": model, "backend": "openai", "mode": mode, "error": None, "cost_usd": None}
    prompt, schema = PROMPTS[mode]
    key = os.environ.get(os.environ.get("GUARD_API_KEY_ENV", ""), "EMPTY")
    mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
    with open(image_path, "rb") as f:
        url = f"data:{mime};base64," + base64.b64encode(f.read()).decode()
    try:
        client = OpenAI(base_url=os.environ["GUARD_BASE_URL"], api_key=key, timeout=timeout, max_retries=0)
        r = client.chat.completions.create(model=model, temperature=0, max_tokens=int(os.environ.get("GUARD_MAX_TOKENS", 4096)),
                                           messages=[{"role": "user", "content": [
                                               {"type": "image_url", "image_url": {"url": url}},
                                               {"type": "text", "text": prompt.replace(READ_LINE, IMAGE_LINE).format(instruction=instruction)
                                                + "\nJSON schema:\n" + json.dumps(schema)}]}])
        obj = _json_text(r.choices[0].message.content)
        out["error"] = _validate(obj, mode)
    except Exception as e:  # noqa: BLE001 - any failure = no verdict (the answer passes)
        obj, out["error"] = None, f"{type(e).__name__}: {str(e)[:200]}"
    if obj is not None and out["error"] is None:
        out.update({k: obj.get(k, "") for k in ("requirements", "verdict", "missing_requirement", "evidence",
                                                 "next_action")})
        out["ok"] = True
    out["latency_s"] = round(time.time() - t0, 1)
    return out


def verify_claude(instruction: str, image_path: str, model: str = DEFAULT_MODEL, timeout: float = TIMEOUT_S,
                  mode: str = "passive") -> dict:
    t0 = time.time()
    out = {"ok": False, "verdict": None, "requirements": [], "missing_requirement": "", "evidence": "",
           "next_action": "", "model": model, "backend": "claude", "mode": mode, "error": None, "cost_usd": None}
    prompt, schema = PROMPTS[mode]
    with tempfile.TemporaryDirectory(prefix="feci_") as work:
        name = "screen" + os.path.splitext(image_path)[1].lower()
        shutil.copy(image_path, os.path.join(work, name))
        cmd = [CLAUDE, "-p", prompt.format(instruction=instruction, image_name=name),
               "--model", model, "--output-format", "json", "--json-schema", json.dumps(schema),
               "--tools", "Read", "--allowedTools", "Read", "--strict-mcp-config", "--setting-sources", "",
               "--no-session-persistence"]
        env = {k: v for k, v in os.environ.items() if not k.startswith("ARGOS")}
        try:
            p = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=timeout, env=env,
                               stdin=subprocess.DEVNULL)
            obj, out["cost_usd"], out["error"] = _parse(p.stdout, mode)
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


def render(v: dict) -> str:
    """Human-readable ✓/✗ checklist of one verdict (for the episode journal)."""
    mark = {"yes": "✓", "no": "✗", "cannot_tell": "?"}
    lines = [f"verdict: {v.get('verdict') or 'NO VERDICT (' + str(v.get('error')) + ')'}  "
             f"[{v.get('backend')}:{v.get('model')}, {v.get('latency_s')} s]"]
    lines += [f"  {mark.get(r.get('status'), '?')} {r.get('requirement')} — {r.get('evidence')}"
              for r in v.get("requirements", [])]
    if v.get("verdict") in ("INCOMPLETE", "NEED_CHECK"):
        lines.append(f"  missing: {v.get('missing_requirement')} | next: {v.get('next_action')}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--mode", default="passive", choices=["passive", "active"])
    a = ap.parse_args()
    v = verify(a.task, a.image, a.model, mode=a.mode)
    print(render(v))
    print(json.dumps(v, ensure_ascii=False))
