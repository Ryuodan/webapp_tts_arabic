"""Auto-Compose agent — turn a job + voice preferences into a ready-to-synthesize
Arabic script and model-aware voice parameters, via one OpenAI structured-output call.

Used by the gateway's POST /api/compose endpoint (see server.py). The frontend feeds the
result straight into the existing synthesis controls, so every field here must already be
valid for the selected worker — in particular OmniVoice's instruct (a closed EN/ZH vocab).
"""
import os
import pathlib
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

BASE_DIR = pathlib.Path(__file__).parent
load_dotenv(BASE_DIR / ".env")  # load OPENAI_* regardless of how the gateway is launched

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")

# OmniVoice's instruct is a CLOSED voice-design vocabulary (EN/ZH, no Arabic). Gender and age
# are returned in their OWN fields (and sent to the worker as separate form controls, where they
# get appended to the instruct), so the `omnivoice_instruct` FIELD must carry only pitch/style —
# otherwise we'd resend e.g. "female, ..., female" and trip OmniVoice's same-category conflict.
# Filtering against this set is also the safeguard that prevents "Unsupported instruct items".
_INSTRUCT_FIELD_TOKENS = [
    "very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch",
    "whisper",
]
_INSTRUCT_CATEGORY = {
    "very low pitch": "pitch", "low pitch": "pitch", "moderate pitch": "pitch",
    "high pitch": "pitch", "very high pitch": "pitch", "whisper": "style",
}
_VOCAB_SET = {t.lower() for t in _INSTRUCT_FIELD_TOKENS}

_DIALECTS = ("msa", "saudi", "egyptian")
_GENDERS = ("", "male", "female")
_AGES = ("", "young", "middle", "old")
_TIMESTEPS = (5, 10, 20)

# Job presets: id -> (Arabic label, English tone brief injected into the prompt).
JOBS = {
    "customer_service": ("خدمة العملاء", "warm, patient, professional customer-support agent helping resolve an issue"),
    "booking":          ("وكيل حجوزات",  "helpful booking / reservations agent confirming details clearly and politely"),
    "storytelling":     ("سرد قصة",      "expressive narrator telling a short, engaging story with rhythm and pauses"),
    "announcement":     ("إعلان",        "clear, confident public announcement or promo with an energetic close"),
}

_DIALECT_GUIDE = {
    "msa":      "Modern Standard Arabic (الفصحى) — formal, broadcast register.",
    "saudi":    "Saudi (Najdi) colloquial Arabic — natural everyday Gulf/Saudi phrasing.",
    "egyptian": "Egyptian colloquial Arabic — natural everyday Cairene phrasing.",
}


class ComposeResult(BaseModel):
    """Structured, model-aware synthesis parameters for one clip."""
    dialect: Literal["msa", "saudi", "egyptian"] = Field(
        description="Arabic dialect for the script")
    gender: Literal["", "male", "female"] = Field(
        default="", description="Speaker gender, or empty to let the model decide")
    age: Literal["", "young", "middle", "old"] = Field(
        default="", description="Speaker age band, or empty to let the model decide")
    text: str = Field(
        description="The Arabic script to be spoken, in the chosen dialect. Use Arabic "
                    "punctuation (، . … ؛ ؟) to shape natural pauses. No stage directions.")
    omnivoice_instruct: str = Field(
        default="",
        description="OmniVoice ONLY: optional pitch/style tokens chosen strictly from the allowed "
                    "list (NOT gender/age — those go in their own fields); empty otherwise.")
    voxcpm2_style: str = Field(
        default="",
        description="VoxCPM2 ONLY: a short free-form English style cue WITHOUT parentheses, "
                    "e.g. 'calm, formal' or 'excited, fast'; empty for other models.")
    cfg_value: float = Field(
        default=2.0, description="VoxCPM2 guidance scale, 1.0-5.0 (higher = stronger adherence)")
    inference_timesteps: int = Field(
        default=10, description="VoxCPM2 diffusion steps: 5 (draft), 10 (balanced) or 20 (quality)")
    notes: str = Field(
        default="", description="One short sentence (Arabic or English) explaining the voice/tone choice")


def _system_prompt() -> str:
    return (
        "You are a voice director for an Arabic text-to-speech studio that has TWO engines: "
        "OmniVoice and VoxCPM2. Given a job and voice preferences, write ONE short, natural "
        "Arabic SCRIPT and choose voice settings for BOTH engines (same script for both).\n\n"
        "General rules:\n"
        "- `text` MUST be Arabic in the requested dialect register; concise (~1-4 sentences) "
        "unless the brief asks for more.\n"
        "- Shape pauses with Arabic punctuation (، . … ؛ ؟). No stage directions, emojis, or "
        "Latin transliteration inside `text`.\n"
        "- Return gender/age in the `gender` and `age` fields. Respect any gender/age/dialect the "
        "user fixed; otherwise pick what best fits the job and character.\n\n"
        "OmniVoice settings:\n"
        "- `omnivoice_instruct` is a CLOSED vocabulary for pitch/style ONLY — at most one pitch "
        "plus optionally 'whisper', chosen strictly from: " + ", ".join(_INSTRUCT_FIELD_TOKENS)
        + ". Empty = neutral. Do NOT put gender, age, accent, Arabic, or emotions here.\n\n"
        "VoxCPM2 settings:\n"
        "- `voxcpm2_style`: a short free-form English delivery cue WITHOUT parentheses "
        "(e.g. 'calm, formal' or 'cheerful, energetic, fast').\n"
        "- `cfg_value`: 1.0-5.0 (≈2.0 natural, higher = stronger style adherence).\n"
        "- `inference_timesteps`: 5 (draft), 10 (balanced) or 20 (best quality)."
    )


def _user_prompt(job, gender, age, dialect, brief) -> str:
    label, tone = JOBS.get(job, (job, ""))
    dialect = dialect if dialect in _DIALECTS else "msa"
    lines = [
        f"Job: {label} ({job}). Intended delivery: {tone}.",
        f"Dialect to use: {dialect} — {_DIALECT_GUIDE[dialect]}",
        f"Gender preference: {gender or 'let you decide'}.",
        f"Age preference: {age or 'let you decide'}.",
    ]
    if (brief or "").strip():
        lines.append(f"Extra context / brief from the user: {brief.strip()}")
    lines.append("Write the script and choose the parameters now.")
    return "\n".join(lines)


def _clamp(v: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo


def _snap_timesteps(v) -> int:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 10
    return min(_TIMESTEPS, key=lambda t: abs(t - v))


def _filter_instruct(instruct: str) -> str:
    """Keep only valid pitch/style tokens, at most one per category — drops anything
    hallucinated or conflicting so OmniVoice never rejects the instruct."""
    items = [p.strip().lower() for p in (instruct or "").replace("，", ",").split(",")]
    kept, used_cats = [], set()
    for it in items:
        cat = _INSTRUCT_CATEGORY.get(it)
        if it in _VOCAB_SET and cat not in used_cats:
            kept.append(it)
            used_cats.add(cat)
    return ", ".join(kept)


def _build_llm():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set (add it to .env or the environment).")
    from langchain_openai import ChatOpenAI
    kwargs = {"model": OPENAI_MODEL, "timeout": 60, "max_retries": 2}
    # GPT-5.x reasoning models reject a custom temperature; only pass one if explicitly set.
    temp = os.getenv("OPENAI_TEMPERATURE", "").strip()
    if temp:
        try:
            kwargs["temperature"] = float(temp)
        except ValueError:
            pass
    return ChatOpenAI(**kwargs).with_structured_output(ComposeResult)


def compose(job: str, gender: str = "", age: str = "",
            dialect: str = "msa", brief: str = "") -> dict:
    """One Arabic script + sanitized settings for BOTH engines (OmniVoice + VoxCPM2)."""
    llm = _build_llm()
    result: ComposeResult = llm.invoke([
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": _user_prompt(job, gender, age, dialect, brief)},
    ])

    # ── sanitize: user-fixed prefs win; everything else clamped to valid ranges ──
    out_dialect = dialect if dialect in _DIALECTS else (
        result.dialect if result.dialect in _DIALECTS else "msa")
    out_gender = gender if gender in _GENDERS and gender else (
        result.gender if result.gender in _GENDERS else "")
    out_age = age if age in _AGES and age else (
        result.age if result.age in _AGES else "")

    return {
        "dialect": out_dialect,
        "gender": out_gender,
        "age": out_age,
        "text": (result.text or "").strip(),
        # OmniVoice: pitch/style instruct (gender/age ride separate form fields)
        "omnivoice_instruct": _filter_instruct(result.omnivoice_instruct),
        # VoxCPM2: free style cue + sampling settings
        "voxcpm2_style": (result.voxcpm2_style or "").strip().strip("()"),
        "cfg_value": round(_clamp(result.cfg_value, 1.0, 5.0), 1),
        "inference_timesteps": _snap_timesteps(result.inference_timesteps),
        "notes": (result.notes or "").strip(),
        "openai_model": OPENAI_MODEL,
    }
