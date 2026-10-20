"""
Assignment 6: the AI layer of Unopsis.

    guardrails.py   cleaning, prompt-injection screening, JSON parsing and validation,
                    and the rule-based fallback used whenever a model is unavailable
    prompts.py      the triage prompt (few-shot, chosen in llm-test/ai_prototype.ipynb)
                    and the brief-writing prompt
    local_llm.py    the local Hugging Face model, loaded lazily with `transformers`
    groq_client.py  the external API (Groq, OpenAI-compatible chat completions)
    pipeline.py     the hybrid pipeline: local model filters, Groq writes the brief

Nothing in this package is imported at Django start-up time by anything that would pull in
torch. The local model is loaded on the first request that needs it, so `manage.py check`,
the test suite and the PythonAnywhere deployment all work on a machine without torch.
See README_AI.md for the full workflow.
"""
