# Background agents and self-improvement

Both run on your own machines and cost nothing extra unless you point them at a paid
provider (which the paid budget still caps).

## Background agents

Loki hands self-contained work to background agents that keep going while you chat:

- **You:** tick **Run in background** next to Send. The built-in Loki agent works on it in
  its own git worktree.
- **Loki itself:** for a large job (the first layer marks it "team"), Loki uses the
  `delegate` tool to hand parts to its agents (Researcher, Builder, Reviewer, Tester); you
  approve each one. Finished work is verified before Loki reports DONE.
- **Another machine:** a linked Mac can send a job to the PC (Settings > Machines).

Running work shows above the message box with its status, output and Stop. Where jobs can
run (this computer, herdr, a cua virtual computer) and the safety rules are in
[operations/BACKGROUND_WORKERS.md](operations/BACKGROUND_WORKERS.md).

## Self-improvement (the RTX 3070 Ti loop)

What it does, and does not, do:

1. **Logs every request** with an honest outcome: `verified` only when it finished DONE
   and every changed file passed its check.
2. **Learns routing**: providers that actually get verified results move up - but only
   within their cost tier and only after 10 judged requests. Free always stays ahead of
   paid.
3. **Collects training data** only from verified successes (secrets masked; your memory
   and profile are replaced by a generic prompt, so they never end up in model weights).
4. **Fine-tunes** a small model (Qwen3-4B, QLoRA, 4-bit) on the GPU once there are 200
   new examples, and registers it in Ollama as a *candidate*.
5. **Promotes it only if it wins**: the candidate must beat the local model it would
   replace on held-out tasks. If it does not, it is discarded and nothing changes.

It does not retrain the cloud models, and it will not improve anything until real
verified work has accumulated - expect weeks of normal use before the first training run.

### Set it up on the Windows PC (once)

```bat
cd C:\Users\macul\Documents\loki
git pull
setup.bat
tools\setup_training.bat
harness_data\.venv\Scripts\python.exe tools\self_improve.py status
harness_data\.venv\Scripts\python.exe tools\self_improve.py schedule
```

`setup_training.bat` installs PyTorch + Unsloth into `harness_data\train_venv` (several
GB). `schedule` adds a nightly Windows task (03:30; `--at HH:MM` to change) that runs
`cycle`: it does nothing until there is enough new data, and never trains while the GPU
is busy (a game or a render).

You also need [Ollama](https://ollama.com) running, with the comparison model pulled:
`ollama pull qwen3:8b`.

### Commands

```
python tools/self_improve.py status            what has been gathered, GPU, past runs
python tools/self_improve.py cycle --force     run the whole loop now, ignoring thresholds
python tools/self_improve.py train --force --max-steps 30   a quick trial training run
```

### Settings (`harness_data/.env`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `LOKI_EXPERIENCE` | 1 | record requests (0 = off) |
| `LOKI_LEARN_ROUTING` | 1 | reorder providers by measured success |
| `LOKI_LEARN_MIN_SAMPLES` | 10 | judged requests before a provider can move |
| `LOKI_TRAIN_MIN_NEW` | 200 | new verified examples before training |
| `LOKI_PROMOTE_MARGIN` | 0.02 | how much better the candidate must score |
| `LOKI_EVAL_BASELINE` | qwen3:8b | the Ollama model the candidate must beat |
| `LOKI_TUNED_PROMOTED` | 0 | set to 1 by `promote`; routes `loki-tuned` |
| `LOKI_PAID_MAX_CALLS` | 40 | model calls per request on a paid provider |

### How it is measured

The evaluation is a cheap proxy: for each held-out task the model sees the conversation up
to the first assistant turn and must make the same kind of first move the verified run
made (the same tool, or a text answer). It is a sanity gate against regressions, not a
full replay of tasks.
