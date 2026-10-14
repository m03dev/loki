"""QLoRA fine-tune a small local model on Loki's verified work, then export it for Ollama.

Runs in the TRAINING environment (tools/setup_training.bat or .sh), not Loki's own venv:
it needs a CUDA GPU, PyTorch and Unsloth. Sized for an 8 GB card such as an RTX 3070 Ti:
a 4B instruct model in 4-bit, LoRA r=16, 2048 tokens, batch 1 x 8 accumulation.

    python tools/train_lora.py --data harness_data/experience/dataset --out harness_data/experience/runs/<id>

Input:  <data>/train.jsonl - one {"messages": [...], "tools": [...]} per line
        (written by experience.build_dataset from DONE + verified trajectories).
Output: <out>/lora/            the adapter (small; keep it)
        <out>/gguf/*.gguf      the merged model, quantized (q4_k_m by default)
        <out>/gguf/Modelfile   for `ollama create`
        <out>/train_report.json

Only the assistant turns are trained on (train_on_responses_only): the model learns what
to DO, not to imitate tool output or the user.
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
import time
from pathlib import Path

DEFAULT_BASE = "unsloth/Qwen3-4B-Instruct-2507"
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def _kwargs_for(cls, wanted: dict) -> dict:
    """Keep only the arguments this version of a class accepts (trl renames them often)."""
    try:
        params = inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):
        return wanted
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return wanted
    return {k: v for k, v in wanted.items() if k in params}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--max-seq", type=int, default=2048)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=0, help="0 = use --epochs")
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--quant", default="q4_k_m")
    ap.add_argument("--no-gguf", action="store_true", help="train only; skip the export")
    args = ap.parse_args()

    train_file = args.data / "train.jsonl"
    if not train_file.is_file() or not train_file.read_text(encoding="utf-8").strip():
        print("[train] no training data at %s - build it with self_improve.py dataset" % train_file)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.time()

    # Unsloth must be imported before transformers/trl so its patches apply.
    try:
        import unsloth  # noqa: F401
        from unsloth import FastLanguageModel
        from unsloth.chat_templates import train_on_responses_only
    except ImportError as exc:
        print("[train] Unsloth is not installed in this environment (%s).\n"
              "        Run tools/setup_training.bat (Windows) or tools/setup_training.sh first,\n"
              "        and run this script with that environment's python." % exc)
        return 3
    import torch
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    if not torch.cuda.is_available():
        print("[train] no CUDA GPU visible to PyTorch - training needs one (e.g. the 3070 Ti).")
        return 4
    gpu = torch.cuda.get_device_name(0)
    vram = torch.cuda.get_device_properties(0).total_memory / 2**30
    print("[train] GPU: %s (%.1f GB)" % (gpu, vram))

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base, max_seq_length=args.max_seq, load_in_4bit=True, dtype=None)
    model = FastLanguageModel.get_peft_model(
        model, r=args.rank, lora_alpha=args.rank, lora_dropout=0.0, bias="none",
        target_modules=TARGET_MODULES, use_gradient_checkpointing="unsloth", random_state=3407)

    # Render in plain Python: loading nested tool calls through Arrow would merge every
    # tool's argument schema into one struct and inject None fields into each call.
    rows, dropped = [], 0
    for line in train_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        example = json.loads(line)
        text = tokenizer.apply_chat_template(example["messages"], tools=example.get("tools") or None,
                                             tokenize=False, add_generation_prompt=False)
        if len(tokenizer(text).input_ids) > args.max_seq:
            dropped += 1
            continue
        rows.append({"text": text})
    print("[train] %d examples (%d dropped as longer than %d tokens)" % (len(rows), dropped, args.max_seq))
    if not rows:
        print("[train] nothing fits in --max-seq; raise it or gather shorter tasks")
        return 5
    dataset = Dataset.from_list(rows)

    config = SFTConfig(**_kwargs_for(SFTConfig, {
        "output_dir": str(args.out / "checkpoints"),
        "dataset_text_field": "text",
        "max_seq_length": args.max_seq, "max_length": args.max_seq,
        "per_device_train_batch_size": 1, "gradient_accumulation_steps": 8,
        "num_train_epochs": args.epochs, "max_steps": args.max_steps if args.max_steps > 0 else -1,
        "learning_rate": args.lr, "warmup_steps": 5, "weight_decay": 0.001,
        "lr_scheduler_type": "linear", "optim": "adamw_8bit", "seed": 3407,
        "logging_steps": 5, "save_strategy": "no", "report_to": "none", "packing": False,
    }))
    trainer_kwargs = {"model": model, "train_dataset": dataset, "args": config}
    trainer_params = inspect.signature(SFTTrainer.__init__).parameters
    trainer_kwargs["processing_class" if "processing_class" in trainer_params else "tokenizer"] = tokenizer
    trainer = SFTTrainer(**trainer_kwargs)
    # Qwen chat markers: learn the assistant turns only.
    trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n",
                                      response_part="<|im_start|>assistant\n")
    stats = trainer.train()
    peak = torch.cuda.max_memory_reserved() / 2**30

    model.save_pretrained(str(args.out / "lora"))
    tokenizer.save_pretrained(str(args.out / "lora"))
    gguf_file = ""
    if not args.no_gguf:
        gguf_dir = args.out / "gguf"
        model.save_pretrained_gguf(str(gguf_dir), tokenizer, quantization_method=args.quant)
        ggufs = sorted(gguf_dir.glob("*.gguf"), key=lambda p: p.stat().st_size)
        if not ggufs:
            print("[train] export produced no .gguf file")
            return 6
        gguf_file = str(ggufs[-1])
        modelfile = gguf_dir / "Modelfile"
        if not modelfile.is_file():   # Unsloth writes one when it knows the template
            modelfile.write_text("FROM ./%s\n" % ggufs[-1].name, encoding="utf-8")

    report = {"base": args.base, "examples": len(dataset), "gpu": gpu, "vram_gb": round(vram, 1),
              "peak_vram_gb": round(peak, 2), "train_loss": getattr(stats, "training_loss", None),
              "seconds": round(time.time() - started), "gguf": gguf_file, "quant": args.quant,
              "rank": args.rank, "max_seq": args.max_seq}
    (args.out / "train_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("[train] done: " + json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
