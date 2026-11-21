# Worker Setup

Install on any machine with Python 3.10+ (Linux/macOS full support incl. rlimits; Windows
runs without POSIX rlimits — treat as trusted environment only until container isolation
lands):

```bash
pip install -e ./worker        # from a clone of this repo
omnimcp-worker report          # print local capability report
```

## Register + run

```bash
omnimcp-worker register --server https://omnimcp.example.com --name build-box
# prints worker_id and token; token saved to ./worker-credentials.json (gitignored)
omnimcp-worker run --server https://omnimcp.example.com
```

Options: `--ram-mb`, `--max-ram-mb`, `--allow-shell` (trusting operators only),
poll/heartbeat intervals.

## What the agent does

- registers with a full capability report (OS, arch, CPU, RAM, disk, GPU probe,
  runtimes: python/node/docker/cargo detected)
- heartbeats (default 10s) and polls for claims (default 2s), exponential backoff offline
- executes claimed jobs in a bounded subprocess (RLIMIT_AS/RLIMIT_CPU/RLIMIT_NPROC,
  own process group), streams logs back, honors server cancellation
- exits cleanly on SIGTERM/SIGINT

## Security notes

- Store `worker-credentials.json` carefully (chmod 600); the token is a 30-day JWT.
- The worker executes job commands on **your machine**. Only run workers on machines you
  control and only against control planes you trust.
