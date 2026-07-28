"""The two LLM agents: compose.py (script + engine settings) and textprep.py (text rewrite).

No network: `langchain_openai.ChatOpenAI` is faked. The value here is the sanitisation
around the model — a hallucinated instruct token or an out-of-range cfg would be rejected
by the worker at synthesis time, so it has to be caught before it leaves the agent.
"""
import pytest

import compose as compose_mod
import textprep as textprep_mod
from compose import ComposeResult, _clamp, _filter_instruct, _snap_timesteps, _user_prompt
from textprep import PrepareResult, _system_prompt


# ══ compose: instruct sanitisation ════════════════════════════
@pytest.mark.parametrize("raw,expected", [
    ("low pitch", "low pitch"),
    ("whisper", "whisper"),
    ("low pitch, whisper", "low pitch, whisper"),          # one per category is fine
    ("LOW PITCH,  Whisper ", "low pitch, whisper"),        # case/space tolerant
    ("low pitch，whisper", "low pitch, whisper"),           # full-width comma from the model
])
def test_filter_instruct_keeps_valid_tokens(raw, expected):
    assert _filter_instruct(raw) == expected


@pytest.mark.parametrize("raw", [
    "female", "elderly", "Saudi Arabic", "excited", "arb", "", None, "   ",
])
def test_filter_instruct_drops_everything_outside_the_closed_vocab(raw):
    """OmniVoice answers an unknown instruct item with a hard error — nothing else may pass."""
    assert _filter_instruct(raw) == ""


def test_filter_instruct_keeps_only_the_first_token_per_category():
    """Two pitches would trip OmniVoice's same-category conflict check."""
    assert _filter_instruct("low pitch, high pitch") == "low pitch"


def test_filter_instruct_strips_gender_but_keeps_the_rest():
    assert _filter_instruct("female, low pitch, arabic") == "low pitch"


# ══ compose: numeric sanitisation ═════════════════════════════
@pytest.mark.parametrize("value,expected", [
    (3.0, 3.0), (0.5, 1.0), (9.9, 5.0), ("2.5", 2.5), ("abc", 1.0), (None, 1.0),
])
def test_clamp_keeps_cfg_in_the_engines_range(value, expected):
    assert _clamp(value, 1.0, 5.0) == expected


@pytest.mark.parametrize("value,expected", [
    (5, 5), (10, 10), (20, 20), (7, 5), (13, 10), (100, 20), (0, 5),
    ("10", 10), ("bad", 10), (None, 10),
])
def test_snap_timesteps_lands_on_a_supported_value(value, expected):
    assert _snap_timesteps(value) == expected


# ══ compose: prompt assembly ══════════════════════════════════
def test_user_prompt_carries_the_job_and_brief():
    prompt = _user_prompt("booking", "female", "young", "egyptian", "  عميل مميز  ")
    assert "وكيل حجوزات" in prompt and "booking" in prompt
    assert "Egyptian colloquial" in prompt
    assert "female" in prompt and "young" in prompt
    assert "عميل مميز" in prompt


def test_user_prompt_says_let_you_decide_when_unset():
    prompt = _user_prompt("storytelling", "", "", "msa", "")
    assert prompt.count("let you decide") == 2
    assert "Extra context" not in prompt


def test_user_prompt_falls_back_to_msa_for_an_unknown_dialect():
    assert "Modern Standard Arabic" in _user_prompt("announcement", "", "", "klingon", "")


# ══ compose: end to end with a faked model ════════════════════
def make_result(**overrides):
    base = dict(dialect="msa", gender="male", age="old", text="  نص مؤلَّف  ",
                omnivoice_instruct="female, high pitch", voxcpm2_style="(calm, formal)",
                cfg_value=9.0, inference_timesteps=13, notes="  ملاحظة  ")
    base.update(overrides)
    return ComposeResult(**base)


def test_compose_sanitises_everything_the_model_returned(fake_llm):
    fake_llm["result"] = make_result()

    out = compose_mod.compose("booking")

    assert out["text"] == "نص مؤلَّف"                    # trimmed
    assert out["omnivoice_instruct"] == "high pitch"    # gender dropped, pitch kept
    assert out["voxcpm2_style"] == "calm, formal"       # parentheses stripped
    assert out["cfg_value"] == 5.0                      # clamped
    assert out["inference_timesteps"] == 10             # snapped
    assert out["notes"] == "ملاحظة"


def test_compose_lets_user_preferences_win(fake_llm):
    fake_llm["result"] = make_result(dialect="msa", gender="male", age="old")

    out = compose_mod.compose("booking", gender="female", age="young", dialect="saudi")

    assert (out["dialect"], out["gender"], out["age"]) == ("saudi", "female", "young")


def test_compose_defers_to_the_model_when_the_user_left_it_open(fake_llm):
    fake_llm["result"] = make_result(gender="female", age="middle")
    out = compose_mod.compose("booking", gender="", age="")
    assert out["gender"] == "female" and out["age"] == "middle"


def test_compose_sends_both_prompts(fake_llm):
    fake_llm["result"] = make_result()
    compose_mod.compose("storytelling", brief="قصة قصيرة")
    roles = [m["role"] for m in fake_llm["messages"]]
    assert roles == ["system", "user"]
    assert "voice director" in fake_llm["messages"][0]["content"]
    assert "قصة قصيرة" in fake_llm["messages"][1]["content"]
    assert fake_llm["schema"] is ComposeResult


def test_compose_without_an_api_key_raises_a_runtime_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        compose_mod.compose("booking")


def test_compose_omits_temperature_for_reasoning_models(fake_llm, monkeypatch):
    monkeypatch.delenv("OPENAI_TEMPERATURE", raising=False)
    fake_llm["result"] = make_result()
    compose_mod.compose("booking")
    assert "temperature" not in fake_llm["init_kwargs"]


@pytest.mark.parametrize("raw,expected", [("0.7", 0.7), ("not-a-number", None)])
def test_compose_passes_an_explicit_temperature_through(fake_llm, monkeypatch, raw, expected):
    monkeypatch.setenv("OPENAI_TEMPERATURE", raw)
    fake_llm["result"] = make_result()
    compose_mod.compose("booking")
    assert fake_llm["init_kwargs"].get("temperature") == expected


def test_compose_job_ids_have_labels_and_tone_briefs():
    for job, (label, tone) in compose_mod.JOBS.items():
        assert label.strip() and tone.strip(), job


# ══ textprep ══════════════════════════════════════════════════
@pytest.mark.parametrize("text,normalize,diacritize", [
    ("نص", False, False),      # nothing requested
    ("", True, True),          # nothing to work on
    ("   ", True, False),
])
def test_prepare_text_short_circuits_without_calling_the_model(text, normalize, diacritize,
                                                               monkeypatch):
    monkeypatch.setattr(textprep_mod, "_build_llm",
                        lambda: pytest.fail("must not build an LLM"))
    out = textprep_mod.prepare_text(text, "msa", normalize, diacritize)
    assert out["text"] == text.strip()
    assert out["normalized"] == "" and out["diacritized"] == ""


def test_prepare_text_returns_each_stage_separately(fake_llm):
    fake_llm["result"] = PrepareResult(normalized="ألفين وستة وعشرين",
                                       diacritized="أَلْفَيْن وَسِتَّة وَعِشْرِين",
                                       notes="  تم تحويل الأرقام  ")

    out = textprep_mod.prepare_text("2026", "msa", normalize=True, diacritize=True)

    assert out["original"] == "2026"
    assert out["normalized"] == "ألفين وستة وعشرين"
    assert out["diacritized"] == "أَلْفَيْن وَسِتَّة وَعِشْرِين"
    assert out["text"] == out["diacritized"]      # diacritized wins when both ran
    assert out["notes"] == "تم تحويل الأرقام"


def test_prepare_text_prefers_normalized_when_tashkeel_is_off(fake_llm):
    fake_llm["result"] = PrepareResult(normalized="خمسة وعشرين بالمئة",
                                       diacritized="ignored because not requested")
    out = textprep_mod.prepare_text("25%", "msa", normalize=True, diacritize=False)
    assert out["diacritized"] == ""              # blanked: the stage was not requested
    assert out["text"] == "خمسة وعشرين بالمئة"


def test_prepare_text_never_returns_an_empty_string(fake_llm):
    """A model that answers with blanks must not wipe the user's text."""
    fake_llm["result"] = PrepareResult(normalized="", diacritized="")
    out = textprep_mod.prepare_text("نص أصلي", "msa", normalize=True, diacritize=True)
    assert out["text"] == "نص أصلي"


def test_prepare_text_falls_back_to_msa(fake_llm):
    fake_llm["result"] = PrepareResult(normalized="x")
    textprep_mod.prepare_text("نص", "klingon", normalize=True)
    assert "Modern Standard Arabic" in fake_llm["messages"][0]["content"]


def test_prepare_text_reports_which_transforms_ran(fake_llm):
    fake_llm["result"] = PrepareResult(normalized="x")
    out = textprep_mod.prepare_text("نص", "msa", normalize=True, diacritize=False)
    assert out["normalize"] is True and out["diacritize"] is False
    assert "normalize" in fake_llm["messages"][1]["content"]
    assert "diacritize" not in fake_llm["messages"][1]["content"]


@pytest.mark.parametrize("normalize,diacritize,present,absent", [
    (True, False, "NORMALIZE for speech", "DIACRITIZE"),
    (False, True, "DIACRITIZE", "NORMALIZE for speech"),
])
def test_system_prompt_only_asks_for_the_requested_transforms(normalize, diacritize,
                                                              present, absent):
    prompt = _system_prompt("msa", normalize, diacritize)
    assert present in prompt and absent not in prompt


def test_system_prompt_bases_tashkeel_on_the_normalized_text_when_both_run():
    assert "take the normalized text" in _system_prompt("msa", True, True)
    assert "take the original text" in _system_prompt("msa", False, True)


def test_prepare_text_without_an_api_key_raises_a_runtime_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        textprep_mod.prepare_text("نص", "msa", normalize=True)
