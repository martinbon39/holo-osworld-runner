# holo-osworld-runner

Research project **Holo-neurochir**: we edit the weights of the computer-use model Holo-3.1-4B
(weight-space steering) and measure the effect on OSWorld tasks.

This repository only runs OSWorld episodes on GitHub-hosted runners (KVM available), one VM per job:

- `.github/workflows/osworld.yml`: `workflow_dispatch` with `arm`, `port`, `served_model`, `meta_json`
  (`tasks/*.json`, `{domain: [ids]}`), `n_shards`, `max_steps`. Job *i* runs shard *i* (round-robin over sorted tasks).
- `patches/rtg-a763361.patch`: our local patches on [RealtimeGUI](https://github.com/1azybug/RealtimeGUI) @ `a763361`
  (container memory limit, ports bound to 127.0.0.1, iptables-nft network script).
- `scripts/`: shard splitter, SSH tunnel to the model server, verify-prompt entry point, nft network script.

The model is served by vLLM elsewhere and reached through an SSH tunnel; credentials live in repository secrets.
Results (`result.txt`, `traj.jsonl`, screenshots) are uploaded as one artifact per shard, named `<arm>[-tag]-<shard>`.

Dispatch example:

    gh workflow run osworld.yml -f arm=orig -f port=8000 -f served_model=Holo-3.1-4B -f meta_json=tasks/pilot1.json -f n_shards=1
