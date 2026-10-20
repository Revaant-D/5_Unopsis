"""
The local Hugging Face model (AI feature 1: message triage).

The model named by settings.AI_LOCAL_MODEL (default ibm-granite/granite-3.3-2b-instruct, the
"sweet spot" from llm-test/ai_prototype.ipynb) is loaded with `transformers` the first time a request
needs it. The first load DOWNLOADS the weights from the Hugging Face Hub into the local cache
(~/.cache/huggingface on Mac/Linux, C:\\Users\\<you>\\.cache\\huggingface on Windows); later
loads read that cache. Nothing is committed to git -- *.safetensors / *.bin are in .gitignore.

Why lazy: importing torch costs seconds and hundreds of MB. Doing it at import time would slow
every `manage.py` command and break the PythonAnywhere deployment, whose free plan cannot hold
torch at all. Instead the import happens inside _load(); if torch/transformers are missing,
LocalModelUnavailable is raised and the caller falls back to the rule-based triage.

One model per process, shared by every request, guarded by a lock so two simultaneous first
requests do not both start a multi-gigabyte download.
"""

import threading
import time

from django.conf import settings

from . import guardrails, prompts


class LocalModelUnavailable(Exception):
    """torch/transformers are not installed, local AI is switched off, or the load failed."""


_lock = threading.Lock()
_loaded = {}  # {"name": str, "tokenizer": ..., "model": ..., "device": str}


def model_name():
    return getattr(settings, "AI_LOCAL_MODEL", "ibm-granite/granite-3.3-2b-instruct")


def is_loaded():
    return bool(_loaded)


def _load():
    if not getattr(settings, "AI_LOCAL_ENABLED", True):
        raise LocalModelUnavailable("Local AI is switched off (AI_LOCAL_ENABLED=False).")
    if _loaded:
        return _loaded
    with _lock:
        if _loaded:
            return _loaded
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise LocalModelUnavailable(
                "torch and transformers are not installed (pip install -r requirements.txt)."
            ) from exc

        name = model_name()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        # float16 on a GPU. On CPU, settings.AI_LOCAL_CPU_DTYPE: bfloat16 by default (~5 GB of RAM
        # for the default model, as in the notebook's laptop run); float32 doubles that.
        cpu_dtype = getattr(torch, getattr(settings, "AI_LOCAL_CPU_DTYPE", "bfloat16"), torch.bfloat16)
        dtype = torch.float16 if device == "cuda" else cpu_dtype
        try:
            tokenizer = AutoTokenizer.from_pretrained(name)
            model = AutoModelForCausalLM.from_pretrained(name, torch_dtype=dtype)
        except Exception as exc:  # network down, wrong name, out of memory...
            raise LocalModelUnavailable(f"Could not load {name}: {exc}") from exc
        model.to(device)
        model.eval()
        _loaded.update(name=name, tokenizer=tokenizer, model=model, device=device)
        return _loaded


def generate(chat, max_new_tokens=None):
    """Run one chat through the local model and return the reply text (greedy decoding)."""
    loaded = _load()
    import torch

    tokenizer, model = loaded["tokenizer"], loaded["model"]
    max_new_tokens = max_new_tokens or getattr(settings, "AI_LOCAL_MAX_NEW_TOKENS", 80)
    # enable_thinking=False switches Qwen3's reasoning mode off; other chat templates ignore it.
    inputs = tokenizer.apply_chat_template(
        chat, add_generation_prompt=True, return_tensors="pt", return_dict=True,
        enable_thinking=False,
    ).to(loaded["device"])
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,  # deterministic: the same message triages the same way every time
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
        )
    new_tokens = output[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def triage(text):
    """
    Triage one message. Always returns a dict, never raises:

        {"lane", "summary", "deadline",       -- the validated answer
         "source": "local" | "rules",          -- who produced it
         "note": str,                          -- why the rules were used, if they were
         "raw": str, "ms": int, "model": str}
    """
    cleaned = guardrails.clean_message_text(text)
    started = time.perf_counter()
    raw, note = "", ""
    try:
        chat = prompts.build_triage_messages(cleaned, shots=getattr(settings, "AI_TRIAGE_SHOTS", 0))
        raw = generate(chat)
        result = guardrails.validate_triage(guardrails.parse_json_object(raw))
        if result is None:
            note = "The model's answer was not valid triage JSON, so the rules were used."
    except LocalModelUnavailable as exc:
        result, note = None, str(exc)
    except Exception as exc:  # a generation error must not become a 500
        result, note = None, f"Local model error: {exc}"

    source = "local"
    if result is None:
        result, source = guardrails.rule_based_triage(cleaned), "rules"
    result.update(
        source=source, note=note, raw=raw,
        ms=int((time.perf_counter() - started) * 1000), model=model_name(),
    )
    return result
