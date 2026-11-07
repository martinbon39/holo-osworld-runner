"""Write shard i of n of an OSWorld task file ({domain: [ids]}): tasks sorted by (domain, id), round-robin.
Usage: python shard_meta.py <meta.json> <i> <n> <out.json>; prints the number of tasks in the shard."""
import json, sys

meta, i, n, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
assert 0 <= i < n, (i, n)
tasks = sorted((d, t) for d, ids in json.load(open(meta)).items() for t in ids)
assert len(set(tasks)) == len(tasks), "duplicate task in meta file"
shard = {}
for d, t in tasks[i::n]:
    shard.setdefault(d, []).append(t)
json.dump(shard, open(out, "w"), indent=1)
print(sum(map(len, shard.values())))
