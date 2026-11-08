"""Exit 0 when <base_url>/models lists <model>. Usage: check_served.py <base_url> <model> [KEY_ENV]
KEY_ENV: name of the env var holding the key, sent as 'Authorization: Bearer' and as 'x-api-key' (Anthropic's
OpenAI-compatible API lists models with x-api-key). Retries ~5 min for cold starts; stops at once on 401/403 or an
empty key. Never prints the key."""
import json, os, sys, time, urllib.error, urllib.request

url, model = sys.argv[1], sys.argv[2]
key_env = sys.argv[3] if len(sys.argv) > 3 else ""
headers = {}
if key_env:
    key = os.environ.get(key_env, "")
    if not key:
        sys.exit(f"secret/env {key_env} is empty")
    headers = {"Authorization": "Bearer " + key, "x-api-key": key, "anthropic-version": "2023-06-01"}
for _ in range(60):
    try:
        req = urllib.request.Request(url + "/models", headers=headers)
        ids = [m["id"] for m in json.load(urllib.request.urlopen(req, timeout=30))["data"]]
        break
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit(f"{url}: HTTP {e.code} (key rejected)")
        print("models not reachable yet: HTTP", e.code, flush=True)
    except Exception as e:
        print("models not reachable yet:", type(e).__name__, flush=True)
    time.sleep(5)
else:
    sys.exit(f"{url} unreachable")
print("served:", ids)
if model not in ids:
    sys.exit(f"{model} not served")
