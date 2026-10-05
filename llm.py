"""The chat model behind the LLM agents — Groq or OpenAI, picked from the environment.

  LLM_PROVIDER  groq | openai. Unset: groq when GROQ_API_KEY is set, else openai.
  groq          GROQ_API_KEY, GROQ_MODEL (default below), GROQ_REASONING_EFFORT and
                GROQ_BASE_URL (optional)
  openai        OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TEMPERATURE (optional)

Both go through langchain_openai.ChatOpenAI — Groq serves an OpenAI-compatible API — so
switching provider needs no extra package. The callers load .env before using this.
"""
import os

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# The best of Groq's eight chat models on the studio's three jobs in a side-by-side test
# (README → "Which Groq model"): it kept every letter on the most lines when adding
# tashkeel, read every number right and never broke JSON. It thinks before answering, so a
# sentence takes 5-9 s; GROQ_REASONING_EFFORT=low brings that to about 1.3 s for some accuracy.
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
OPENAI_DEFAULT_MODEL = "gpt-5.5"

# Some httpx + brotli combinations cannot decode Groq's compressed replies and report it
# only as a bare "Connection error"; asking for gzip avoids that on any machine.
SAFE_HEADERS = {"Accept-Encoding": "gzip, deflate"}


# Request options per model. The reasoning models think before they answer, and in JSON mode
# an answer that runs out of tokens mid-thought comes back empty, which Groq rejects as
# "Failed to validate JSON": 26% of gpt-oss-120b's and 46% of qwen3.6's tashkeel calls at
# Groq's own budget, at most 2% with these. gpt-oss-20b only stays inside JSON at low effort.
GROQ_MODEL_OPTIONS = {
    "openai/gpt-oss-120b": {"max_completion_tokens": 16384},
    "openai/gpt-oss-20b":  {"max_completion_tokens": 16384, "reasoning_effort": "low"},
    "qwen/qwen3.6-27b":    {"max_completion_tokens": 8192},
}


def groq_options() -> dict:
    """Extra request fields for the chosen Groq model; GROQ_REASONING_EFFORT overrides the
    effort (gpt-oss: low | medium | high; qwen: none | default)."""
    options = dict(GROQ_MODEL_OPTIONS.get(model_name(), {}))
    effort = os.getenv("GROQ_REASONING_EFFORT", "").strip().lower()
    if effort:
        options["reasoning_effort"] = effort
    return options


def provider() -> str:
    chosen = os.getenv("LLM_PROVIDER", "").strip().lower()
    if chosen in ("groq", "openai"):
        return chosen
    return "groq" if os.getenv("GROQ_API_KEY") else "openai"


def model_name() -> str:
    if provider() == "groq":
        return os.getenv("GROQ_MODEL") or GROQ_DEFAULT_MODEL
    return os.getenv("OPENAI_MODEL") or OPENAI_DEFAULT_MODEL


def structured_llm(schema, timeout: int = 60, effort: str = ""):
    """A chat model whose replies parse into `schema` (a pydantic model).

    `effort` is how hard an OpenAI reasoning model thinks about this job (low | medium |
    high); empty leaves it to the model. Groq takes its own from GROQ_REASONING_EFFORT.

    Raises RuntimeError when the chosen provider's key is missing; the gateway turns that
    into a 503 the studio shows as-is.
    """
    if provider() == "groq":
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set (add it to .env or the environment).")
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=model_name(), api_key=key,
                         base_url=os.getenv("GROQ_BASE_URL") or GROQ_BASE_URL,
                         temperature=0, timeout=timeout, max_retries=2,
                         default_headers=SAFE_HEADERS, extra_body=groq_options() or None)
        # JSON mode is the structured output every usable Groq chat model honours; strict
        # json_schema is limited to a few. The callers' prompts spell out the JSON keys.
        return llm.with_structured_output(schema, method="json_mode")

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set (add it to .env or the environment).")
    from langchain_openai import ChatOpenAI
    kwargs = {"model": model_name(), "timeout": timeout, "max_retries": 2}
    if effort:
        kwargs["reasoning_effort"] = effort
    # GPT-5.x reasoning models reject a custom temperature; only pass one if explicitly set.
    temp = os.getenv("OPENAI_TEMPERATURE", "").strip()
    if temp:
        try:
            kwargs["temperature"] = float(temp)
        except ValueError:
            pass
    return ChatOpenAI(**kwargs).with_structured_output(schema)
