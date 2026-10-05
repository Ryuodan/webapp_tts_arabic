"""Text-Prep agent — turn raw Arabic into TTS-friendly Arabic via one OpenAI call.

Two independent, toggleable transforms (the worker/models are NOT touched — this only
rewrites the `text` string BEFORE it reaches OmniVoice / VoxCPM2):

  • normalize  — verbalize digits, dates, times, currency, %, units, ordinals and Latin
                 abbreviations/acronyms into fully spelled-out Arabic WORDS, in the chosen
                 dialect register. Raw "2026" / "25%" / "د." get misread or skipped today.
  • diacritize — add full tashkeel (harakat) so the model reads each word unambiguously.
                 Whether this actually improves OmniVoice/VoxCPM2 output is the open question
                 the UI lets you A/B; hence it stays opt-in and the result stays editable.
                 `marks` thins it out: the shadda alone, or a lite copy the agent writes
                 itself (the shadda and the sukun, added commas and full stops, and a
                 short vowel only where a word could be misread).

Used by the gateway's POST /api/prepare (see server.py). The model — Groq or OpenAI — comes
from llm.py.
"""
import os
import pathlib
import re
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

BASE_DIR = pathlib.Path(__file__).parent
load_dotenv(BASE_DIR / ".env")  # load the LLM keys regardless of how the gateway is launched

import llm  # noqa: E402 — reads the environment .env just filled in

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
# How hard the model thinks about the lite copy (OpenAI reasoning models; empty = its own
# default). At "low" gpt-5.5 wrote one in 11-18 s against 28-59 s at its default, and
# placed the same shaddas (26 of 26) and sukuns (86 of 97) as the full tashkeel either way.
LITE_EFFORT = os.getenv("LITE_REASONING_EFFORT", "low").strip().lower()

# Tashkeel adds marks and nothing else. Every model tested occasionally rewrote a word too
# (الحين → الحالين), which would make an original-vs-tashkeel comparison compare two
# different sentences — so the letters are checked, and a slip gets one corrected retry.
_MARKS = re.compile(r"[\u064B-\u0652\u0670\u0640]")    # harakat, dagger alef, tatweel
_LETTERS = re.compile(r"[\u0621-\u064A]")


def _letters(text: str) -> str:
    return "".join(_LETTERS.findall(_MARKS.sub("", text or "")))


# Which marks the caller wants back: all of them, the shadda alone, or the lite copy. The
# shadda is the one mark that changes a word's consonants (doubling one); the rest only fix
# the short vowels. Lite is the agent's own lighter marking: the shadda and the sukun —
# which consonant is doubled and which has no vowel after it — plus what a careful writer
# adds by hand: commas and full stops, and a short vowel on the odd word that reads two ways
# without one.
MARK_MODES = ("full", "shadda", "lite")
_NOT_SHADDA = re.compile(r"[ً-ِْٰ]")   # every haraka but the shadda
_SHORT_VOWELS = re.compile(r"[ً-ِٰ]")       # every haraka but shadda and sukun


def shadda_only(text: str) -> str:
    """Full tashkeel with everything but the shadda taken off again."""
    return _NOT_SHADDA.sub("", text or "")

_DIALECTS = ("msa", "saudi", "egyptian")
_DIALECT_GUIDE = {
    "msa":      "Modern Standard Arabic (الفصحى) — formal/broadcast register.",
    "saudi":    "Saudi (Najdi) colloquial Arabic — everyday Gulf/Saudi phrasing.",
    "egyptian": "Egyptian colloquial Arabic — everyday Cairene phrasing.",
}


# How a few everyday words carry their harakat in each colloquial register.
_SPOKEN_EXAMPLES = {
    "saudi":    " (e.g. «وِشْ», «الْحِينْ», «أَبْشِرْ», «طَلَبِكْ»)",
    "egyptian": " (e.g. «إِزَّيَّكْ», «دِلْوَقْتِي», «عَايِزْ»)",
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
    lite: str = Field(
        default="",
        description="The lightly marked text: the shadda on every doubled letter, the sukun on "
                    "every consonant with no vowel after it, added commas and full stops, and "
                    "a short vowel only where a word could be misread. Fill ONLY if the lite "
                    "copy was requested; otherwise leave empty.")
    notes: str = Field(
        default="",
        description="One short sentence (Arabic or English) on what was changed, e.g. which "
                    "numbers were spelled out. Empty if nothing changed.")


def _system_prompt(dialect: str, normalize: bool, diacritize: bool, lite: bool = False) -> str:
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
    base = "the normalized text" if normalize else "the original text"
    if diacritize and lite:
        # The agent writes the lite copy itself, as its only job: asked for the full tashkeel
        # beside it, gpt-5.5 took 36-59 s over a Najdi line.
        if dialect == "msa":
            ending = ("In الفصحى most words end in a case or mood vowel, which this copy "
                      "leaves out: the last letter stays bare unless it truly carries a "
                      "sukun (منْ، لمْ، قدْ).")
        else:
            ending = ("This is colloquial speech, where a word ends in a sukun or a long vowel"
                      + _SHORT_VOWELS.sub("", _SPOKEN_EXAMPLES.get(dialect, "")) + ".")
        rules.append(
            f"LITE (تشكيل خفيف): take {base} and mark it the way a careful writer does by "
            "hand, as it is read in this register. Go through the text word by word for "
            "(1) and (2) — a missed shadda or sukun is the costliest mistake here. "
            "(1) Put the shadda on every doubled letter: طيّب، كلّ، محمّد، يكلّم، اللّه, and the "
            "sun letter after «ال» (الشّمس). "
            "(2) Put the sukun on every consonant that is spoken with no vowel after it, "
            "wherever the full tashkeel would put one: inside a word (الدّرْس، أخْبار، يسْتخْدم), "
            "on the lam of «ال» before a moon letter (الْقمر) and at the end of a word. "
            + ending + " Never on a long vowel (ا، و، ي). "
            "(3) Write no fatha, damma, kasra or tanwin, EXCEPT on a word a reader could "
            "take for a different word or say wrongly without help — a homograph "
            "(عَلِم / عِلْم / عَلَم), a passive verb (كُتِب), an uncommon name or a borrowed word. "
            "Give such a word only the one or two of them that settle how it is read; a "
            "word that reads only one way gets none. "
            "(4) Punctuate it for reading aloud: an Arabic comma «،» where a speaker pauses "
            "and a full stop «.» at the end of each sentence («؟» after a question). Keep the "
            "punctuation that is already there; this is the one place where you add any. "
            "Do not change, add or remove a letter or a word.")
    elif diacritize:
        if dialect == "msa":
            how = ("add full, correct harakat (fatha, damma, kasra, sukun, shadda, tanwin) to "
                   "every word so the engine pronounces it unambiguously, including correct "
                   "case/mood endings (الإعراب) for the register.")
        else:
            # Asked for الإعراب, every model put الفصحى endings on colloquial words (أخدمكَ،
            # اليومَ), which reads Najdi text out as MSA.
            how = ("add full harakat (fatha, damma, kasra, sukun, shadda) to every word the way "
                   "it is SPOKEN in this dialect. This is colloquial speech, not الفصحى: do NOT "
                   "add case or mood endings (no tanwin, no final damma/fatha/kasra of الإعراب) — "
                   "a spoken word ends in a sukun or a long vowel"
                   + _SPOKEN_EXAMPLES.get(dialect, "") + ".")
        rules.append(f"DIACRITIZE (تشكيل): take {base} and {how} Do not change the letters.")
    # Spell out exactly which output fields to fill so the UI can show each stage separately.
    fields = []
    if normalize:
        fields.append("`normalized` = verbalized text, NO harakat")
    else:
        fields.append("`normalized` = empty (not requested)")
    if diacritize and not lite:
        fields.append("`diacritized` = " + ("normalized" if normalize else "original")
                      + " text WITH full harakat")
    else:
        fields.append("`diacritized` = empty (not requested)")
    if diacritize and lite:
        fields.append("`lite` = " + ("normalized" if normalize else "original")
                      + " text, lightly marked and punctuated")
    rules.append("Fill the output fields exactly like this: " + "; ".join(fields) + ".")
    rules.append("Answer with a JSON object with exactly the keys `normalized`, `diacritized`"
                 + (", `lite`" if diacritize and lite else "") + " and `notes`.")
    return "Rules:\n- " + "\n- ".join(rules)


def _build_llm(effort: str = ""):
    return llm.structured_llm(PrepareResult, effort=effort)


def prepare_text(text: str, dialect: str = "msa",
                 normalize: bool = True, diacritize: bool = False, marks: str = "full") -> dict:
    """Return {original, normalized, diacritized, text, notes, ...}.

    `text` is the final string to synthesize (diacritized → normalized → original, in that
    order of preference). `normalized`/`diacritized` are the per-stage results for the UI's
    before/after view; each is empty when its transform was not requested. No LLM call when
    nothing is requested or the text is empty.

    `marks` picks what `diacritized` carries: "full" tashkeel, or "shadda" for the shadda
    alone. Either way the model diacritizes the whole sentence once — that is where it
    places the shadda best — and both forms come back (`diacritized_full`,
    `diacritized_shadda`), so a client can switch between them without another call.

    "lite" is a job of its own for the model, which writes that copy itself: the shadda
    and the sukun, added commas and full stops, and a short vowel only on a word that could
    be misread. It comes back as `diacritized_lite`, and the other two forms are empty —
    they were never made.
    """
    text = (text or "").strip()
    dialect = dialect if dialect in _DIALECTS else "msa"
    marks = marks if marks in MARK_MODES else "full"
    base = {"original": text, "normalized": "", "diacritized": "", "text": text,
            "notes": "", "normalize": normalize, "diacritize": diacritize,
            "openai_model": OPENAI_MODEL, "provider": llm.provider(), "model": llm.model_name(),
            "letters_changed": False, "marks": marks, "diacritized_full": "",
            "diacritized_shadda": "", "diacritized_lite": ""}
    if not text or not (normalize or diacritize):
        return base

    lite = diacritize and marks == "lite"
    model = _build_llm(LITE_EFFORT) if lite else _build_llm()
    wanted = ", ".join(w for w, on in (("normalize", normalize),
                                       ("lite" if lite else "diacritize", diacritize)) if on)
    messages = [
        {"role": "system", "content": _system_prompt(dialect, normalize, diacritize, lite)},
        {"role": "user", "content": f"Apply ({wanted}) to this Arabic text and return it:\n\n{text}"},
    ]
    result: PrepareResult = model.invoke(messages)

    def marked(answer: PrepareResult) -> str:     # the one marked copy this call asked for
        return ((answer.lite if lite else answer.diacritized) or "").strip()

    normalized  = (result.normalized or "").strip() if normalize else ""
    diacritized = marked(result) if diacritize else ""

    # Tashkeel alone must keep every letter (normalizing rewrites numbers, so it may not).
    if diacritized and not normalize and _letters(diacritized) != _letters(text):
        retry: PrepareResult = model.invoke(messages + [
            {"role": "assistant", "content": diacritized},
            {"role": "user", "content": "That changed some letters or words. Return the ORIGINAL "
                                        "text with " + ("harakat and punctuation" if lite else "harakat")
                                        + " only — every letter and word exactly "
                                        "as given, nothing added, removed or replaced."},
        ])
        again = marked(retry)
        if again and _letters(again) == _letters(text):
            diacritized = again
        else:
            base["letters_changed"] = True
    full = "" if lite else diacritized
    shadda = shadda_only(full)
    if marks == "shadda":
        diacritized = shadda
    base.update({
        "normalized": normalized,
        "diacritized": diacritized,
        "diacritized_full": full,
        "diacritized_shadda": shadda,
        "diacritized_lite": diacritized if lite else "",
        "text": diacritized or normalized or text,   # never hand back an empty string
        "notes": (result.notes or "").strip(),
    })
    return base
