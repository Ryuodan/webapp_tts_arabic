"""Text-Prep agent — turn raw Arabic into TTS-friendly Arabic via one OpenAI call.

Two independent, toggleable transforms (the worker/models are NOT touched — this only
rewrites the `text` string BEFORE it reaches OmniVoice / VoxCPM2):

  • normalize  — verbalize digits, dates, times, currency, %, units, ordinals and Latin
                 abbreviations/acronyms into fully spelled-out Arabic WORDS, in the chosen
                 dialect register. Raw "2026" / "25%" / "د." get misread or skipped today.
  • diacritize — add full tashkeel (harakat) so the model reads each word unambiguously.
                 Whether this actually improves OmniVoice/VoxCPM2 output is the open question
                 the UI lets you A/B; hence it stays opt-in and the result stays editable.

Used by the gateway's POST /api/prepare (see server.py). Mirrors compose.py's LLM plumbing.
"""
import os
import pathlib
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

BASE_DIR = pathlib.Path(__file__).parent
load_dotenv(BASE_DIR / ".env")  # load OPENAI_* regardless of how the gateway is launched

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")

_DIALECTS = ("msa", "saudi", "egyptian")
_DIALECT_GUIDE = {
    "msa":      "Modern Standard Arabic (الفصحى) — formal/broadcast register.",
    "saudi":    "Saudi (Najdi) colloquial Arabic — everyday Gulf/Saudi phrasing.",
    "egyptian": "Egyptian colloquial Arabic — everyday Cairene phrasing.",
}


class PrepareResult(BaseModel):
    """Each requested transform as its own field, so the UI can show before/after per stage."""
    normalized: str = Field(
        default="",
        description="The text with every number/date/time/percentage/currency/symbol and "
                    "abbreviation verbalized into Arabic WORDS, but WITHOUT any diacritics. "
                    "Fill ONLY if normalization was requested; otherwise leave empty.")
    diacritized: str = Field(
        default="",
        description="The fully diacritized (tashkeel) text. If normalization was ALSO requested, "
                    "this is the normalized text WITH harakat; otherwise it is the ORIGINAL text "
                    "with harakat. Fill ONLY if diacritization was requested; otherwise leave empty.")
    notes: str = Field(
        default="",
        description="One short sentence (Arabic or English) on what was changed, e.g. which "
                    "numbers were spelled out. Empty if nothing changed.")


def _system_prompt(dialect: str, normalize: bool, diacritize: bool) -> str:
    guide = _DIALECT_GUIDE.get(dialect, _DIALECT_GUIDE["msa"])
    rules = [
        "You prepare Arabic text for a text-to-speech engine. You DO NOT translate, summarize, "
        "rephrase for style, add, or remove content. Preserve the exact meaning, word order, "
        "sentence structure, line breaks and Arabic punctuation (، . … ؛ ؟ !).",
        f"Target dialect/register: {dialect} — {guide} Spell numbers and pick wording in THIS register.",
        "Output Arabic script only in `text`. Never include Latin letters, emojis, brackets, "
        "stage directions, or explanations inside `text`.",
    ]
    if normalize:
        rules.append(
            "NORMALIZE for speech: convert every digit, number, date, time, phone number, "
            "currency amount, percentage, ordinal, math symbol (%, +, -, =, /, ×) and unit into "
            "fully spelled-out Arabic WORDS as a human would read them aloud (e.g. 2026 → "
            "«ألفين وستة وعشرين», 25% → «خمسة وعشرين بالمئة», 3.5 كم → «ثلاثة فاصلة خمسة كيلومترات»). "
            "Expand Latin/Arabic abbreviations (د. → «دكتور», م → «متر», SMS → «إس إم إس»); spell "
            "unpronounceable acronyms letter-by-letter in Arabic. Keep already-correct Arabic words unchanged."
        )
    if diacritize:
        base = "the normalized text" if normalize else "the original text"
        rules.append(
            f"DIACRITIZE (تشكيل): take {base} and add full, correct harakat (fatha, damma, kasra, "
            "sukun, shadda, tanwin) to every word so the engine pronounces it unambiguously, "
            "including correct case/mood endings (الإعراب) for the register. Do not change the letters."
        )
    # Spell out exactly which output fields to fill so the UI can show each stage separately.
    fields = []
    if normalize:
        fields.append("`normalized` = verbalized text, NO harakat")
    else:
        fields.append("`normalized` = empty (not requested)")
    if diacritize:
        fields.append("`diacritized` = " + ("normalized" if normalize else "original")
                      + " text WITH full harakat")
    else:
        fields.append("`diacritized` = empty (not requested)")
    rules.append("Fill the output fields exactly like this: " + "; ".join(fields) + ".")
    return "Rules:\n- " + "\n- ".join(rules)


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
    return ChatOpenAI(**kwargs).with_structured_output(PrepareResult)


def prepare_text(text: str, dialect: str = "msa",
                 normalize: bool = True, diacritize: bool = False) -> dict:
    """Return {original, normalized, diacritized, text, notes, ...}.

    `text` is the final string to synthesize (diacritized → normalized → original, in that
    order of preference). `normalized`/`diacritized` are the per-stage results for the UI's
    before/after view; each is empty when its transform was not requested. No LLM call when
    nothing is requested or the text is empty.
    """
    text = (text or "").strip()
    dialect = dialect if dialect in _DIALECTS else "msa"
    base = {"original": text, "normalized": "", "diacritized": "", "text": text,
            "notes": "", "normalize": normalize, "diacritize": diacritize,
            "openai_model": OPENAI_MODEL}
    if not text or not (normalize or diacritize):
        return base

    llm = _build_llm()
    wanted = ", ".join(w for w, on in (("normalize", normalize), ("diacritize", diacritize)) if on)
    result: PrepareResult = llm.invoke([
        {"role": "system", "content": _system_prompt(dialect, normalize, diacritize)},
        {"role": "user", "content": f"Apply ({wanted}) to this Arabic text and return it:\n\n{text}"},
    ])

    normalized  = (result.normalized or "").strip() if normalize else ""
    diacritized = (result.diacritized or "").strip() if diacritize else ""
    base.update({
        "normalized": normalized,
        "diacritized": diacritized,
        "text": diacritized or normalized or text,   # never hand back an empty string
        "notes": (result.notes or "").strip(),
    })
    return base
