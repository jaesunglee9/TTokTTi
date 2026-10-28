# incident_review/eval/stage1_prompt.py
"""Verbatim copy of the realtime detector prompt (vision_bodycam/core/inference.py, core/rag.py default)."""

RULE_CONTEXT = "All workers must wear hard hats (helmets) and high-visibility safety vests at all times."
PROMPT = (
    f"Safety Rules Context: {RULE_CONTEXT}\n"
    "You are a safety inspector viewing the last 3 seconds of a worker's bodycam. "
    "Is the worker wearing required safety gear or performing a safe action? "
    "If there is a safety violation, you MUST start your response exactly with 'DANGER:' followed by a brief 1-sentence explanation of the hazard. "
    "If everything is safe, reply only with 'SAFE'."
)
