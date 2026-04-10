# changdu

`changdu` is a Python CLI that mirrors Dreamina capability with Volcano Ark models:

- Image generation: Seedream 5.0 Lite
- Video generation: Seedance 2.0

## Install

```bash
cd changdu
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Required Environment

```bash
export CHANGDU_ARK_API_KEY="your_ark_api_key"
# optional
export CHANGDU_ARK_BASE_URL="https://ark.cn-beijing.volces.com"
export CHANGDU_SEED_TEXT_ENDPOINT="ep-m-20260328105436-n2x7w"
export CHANGDU_SEEDREAM_ENDPOINT="ep-m-20260403105201-9p9g6"
export CHANGDU_SEEDANCE_ENDPOINT="ep-20260326170052-hjksg"
```

`ARK_API_KEY` is also accepted as a fallback.

You can also set per-run overrides:

```bash
changdu --api-key "<your_key>" \
  --seedream-endpoint "ep-m-20260403105201-9p9g6" \
  --seedance-endpoint "ep-20260326170052-hjksg" \
  auth check
```

## Quick Start

```bash
changdu auth check
```

Generate image:

```bash
changdu image generate \
  --prompt-file ../末班咖啡馆/角色/林晚.prompt.txt \
  --output ./out/linwan.jpg
```

Submit video:

```bash
changdu video generate \
  --prompt-file ../末班咖啡馆/单集制作/EP001/视频_Clip001.prompt.txt \
  --image ../末班咖啡馆/角色/林晚.jpg \
  --image ../末班咖啡馆/角色/陈默.jpg \
  --image ../末班咖啡馆/场景/深夜街角咖啡馆.jpg
```

Query and wait:

```bash
changdu task show <task_id>
changdu task wait <task_id> --output ./out/clip001.mp4
```

## Batch

```bash
changdu batch run ./examples/ep001.batch.yaml
```

Batch spec supports jobs of type `image` and `video`.

## Trajectory

Each command creates a run record in `~/.local/share/changdu/runs` by default:

- `meta.json`
- `events.jsonl`

Inspect:

```bash
changdu trajectory list
changdu trajectory show <run_id>
changdu trajectory export <run_id> --output ./run.json
```
