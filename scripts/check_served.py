"""Exit 0 when <base_url>/models lists <model>. Usage: check_served.py <base_url> <model> <bearer|none>
bearer: sends 'Authorization: Bearer $MODAL_KEY'. Retries for ~5 min (cold starts). Never prints the key."""
import json, os, sys, time, urllib.request

url, model, auth = sys.argv[1], sys.argv[2], sys.argv[3]
headers = {"Authorization": "Bearer " + os.environ["MODAL_KEY"]} if auth == "bearer" else {}
for _ in range(60):
    try:
        req = urllib.request.Request(url + "/models", headers=headers)
        ids = [m["id"] for m in json.load(urllib.request.urlopen(req, timeout=30))["data"]]
        break
    except Exception as e:
        print("models not reachable yet:", type(e).__name__, flush=True)
        time.sleep(5)
else:
    sys.exit(f"{url} unreachable")
print("served:", ids)
if model not in ids:
    sys.exit(f"{model} not served")
