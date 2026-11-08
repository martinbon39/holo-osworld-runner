"""Adds the HTTP headers of $MODEL_AUTH_HEADERS (JSON object) to every openai.OpenAI client, in the main process and in
run_holo's spawned workers (each interpreter imports sitecustomize at startup). Used for a model behind an auth proxy."""
import json, os

_h = os.environ.get("MODEL_AUTH_HEADERS")
if _h:
    import openai

    _headers = json.loads(_h)
    _init = openai.OpenAI.__init__

    def _init_with_headers(self, *a, **kw):
        kw["default_headers"] = {**_headers, **(kw.get("default_headers") or {})}
        _init(self, *a, **kw)

    openai.OpenAI.__init__ = _init_with_headers
