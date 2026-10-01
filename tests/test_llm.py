"""llm.py — which provider and model the agents get — and textprep's letter check.

langchain_openai is replaced by a recorder here, so nothing leaves the machine.
"""
import sys
import types

import pytest

import llm
import textprep


@pytest.fixture
def chat(monkeypatch):
    """A fake langchain_openai.ChatOpenAI recording how it was built and wrapped."""
    rec = {}

    class ChatOpenAI:
        def __init__(self, **kwargs):
            rec["init"] = kwargs

        def with_structured_output(self, schema, **kwargs):
            rec["schema"], rec["structured"] = schema, kwargs
            return self

    monkeypatch.setitem(sys.modules, "langchain_openai",
                        types.SimpleNamespace(ChatOpenAI=ChatOpenAI))
    return rec


# ── provider choice ───────────────────────────────────────────
def test_groq_is_used_when_its_key_is_present(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert llm.provider() == "groq"
    assert llm.model_name() == llm.GROQ_DEFAULT_MODEL


def test_openai_is_used_without_a_groq_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    assert llm.provider() == "openai" and llm.model_name() == "gpt-test"


@pytest.mark.parametrize("chosen", ["openai", " OpenAI "])
def test_llm_provider_overrides_the_key_based_choice(monkeypatch, chosen):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("LLM_PROVIDER", chosen)
    assert llm.provider() == "openai"


def test_an_unknown_provider_name_falls_back_to_the_key_based_choice(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    assert llm.provider() == "groq"


# ── what the agents are handed ────────────────────────────────
def test_groq_goes_through_its_openai_compatible_endpoint(monkeypatch, chat):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    llm.structured_llm(textprep.PrepareResult)
    init = chat["init"]
    assert init["base_url"] == "https://api.groq.com/openai/v1"
    assert init["api_key"] == "gsk_test" and init["model"] == "openai/gpt-oss-120b"
    assert init["temperature"] == 0
    assert init["default_headers"] == {"Accept-Encoding": "gzip, deflate"}
    assert chat["structured"] == {"method": "json_mode"}
    assert chat["schema"] is textprep.PrepareResult


def test_groq_model_and_endpoint_can_be_overridden(monkeypatch, chat):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setenv("GROQ_BASE_URL", "http://proxy.local/v1")
    llm.structured_llm(textprep.PrepareResult)
    assert chat["init"]["model"] == "llama-3.3-70b-versatile"
    assert chat["init"]["base_url"] == "http://proxy.local/v1"


# ── per-model request options ─────────────────────────────────
def test_the_default_model_gets_room_to_think(monkeypatch, chat):
    """Without a token budget a reasoning model can run dry mid-thought and return nothing,
    which Groq rejects as invalid JSON."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    llm.structured_llm(textprep.PrepareResult)
    assert chat["init"]["extra_body"] == {"max_completion_tokens": 16384}


def test_a_model_without_special_needs_gets_no_extra_fields(monkeypatch, chat):
    """An unknown field is a 400 on some models (`reasoning_effort` on minimax, for one)."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    llm.structured_llm(textprep.PrepareResult)
    assert chat["init"]["extra_body"] is None


@pytest.mark.parametrize("model, effort, expected", [
    ("openai/gpt-oss-120b", " Low ", {"max_completion_tokens": 16384, "reasoning_effort": "low"}),
    ("openai/gpt-oss-20b", "", {"max_completion_tokens": 16384, "reasoning_effort": "low"}),
    ("openai/gpt-oss-20b", "medium", {"max_completion_tokens": 16384, "reasoning_effort": "medium"}),
    ("qwen/qwen3.8-27b", "none", {"reasoning_effort": "none"}),
])
def test_reasoning_effort_can_be_set_from_the_environment(monkeypatch, model, effort, expected):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("GROQ_MODEL", model)
    monkeypatch.setenv("GROQ_REASONING_EFFORT", effort)
    assert llm.groq_options() == expected


def test_choosing_groq_without_its_key_says_which_key_is_missing(monkeypatch, chat):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        llm.structured_llm(textprep.PrepareResult)


def test_the_openai_path_is_built_as_before(monkeypatch, chat):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_TEMPERATURE", "0.3")
    llm.structured_llm(textprep.PrepareResult)
    assert chat["init"] == {"model": "gpt-test", "timeout": 60, "max_retries": 2, "temperature": 0.3}
    assert chat["structured"] == {}


def test_openai_without_its_key_still_says_so(monkeypatch, chat):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm.structured_llm(textprep.PrepareResult)


# ── textprep: tashkeel must keep every letter ─────────────────
ORIGINAL = "الحين تقدر تستخدم الخدمة"
GOOD = "الْحِينْ تِقْدَرْ تِسْتَخْدِمْ الْخِدْمَةْ"
REWORDED = "الْحَالَيْنَ تَقْدِرْ تَسْتَخْدِمِ الخِدْمَةَ"     # الحين → الحالين, as one model did


@pytest.fixture
def answers(monkeypatch):
    """textprep's model, answering with the queued diacritized texts in turn."""
    queue, seen = [], []

    class Model:
        def invoke(self, messages):
            seen.append(messages)
            return textprep.PrepareResult(diacritized=queue.pop(0))

    monkeypatch.setattr(textprep, "_build_llm", lambda: Model())
    return queue, seen


def test_tashkeel_that_keeps_the_letters_is_used_as_is(answers):
    queue, seen = answers
    queue.append(GOOD)
    out = textprep.prepare_text(ORIGINAL, "saudi", normalize=False, diacritize=True)
    assert out["diacritized"] == GOOD and out["letters_changed"] is False
    assert len(seen) == 1


def test_a_reworded_answer_gets_one_corrected_retry(answers):
    queue, seen = answers
    queue.extend([REWORDED, GOOD])
    out = textprep.prepare_text(ORIGINAL, "saudi", normalize=False, diacritize=True)
    assert out["diacritized"] == GOOD and out["letters_changed"] is False
    assert len(seen) == 2 and "ORIGINAL" in seen[1][-1]["content"]


def test_a_second_rewording_is_flagged_not_hidden(answers):
    queue, _ = answers
    queue.extend([REWORDED, REWORDED])
    out = textprep.prepare_text(ORIGINAL, "saudi", normalize=False, diacritize=True)
    assert out["letters_changed"] is True
    assert out["diacritized"] == REWORDED            # still shown, so the user can fix it


def test_normalizing_may_change_letters_so_it_is_not_checked(answers):
    queue, seen = answers
    queue.append("خَمْسَةٌ")
    out = textprep.prepare_text("5", "msa", normalize=True, diacritize=True)
    assert out["letters_changed"] is False and len(seen) == 1


# ── textprep: shadda only, or the whole tashkeel ──────────────
FULL = "الْمُعَلِّمُ شَدَّ الْحَبْلَ بِقُوَّةٍ"
SHADDA = "المعلّم شدّ الحبل بقوّة"


def test_shadda_only_keeps_the_shadda_and_drops_every_other_mark():
    assert textprep.shadda_only(FULL) == SHADDA
    assert textprep.shadda_only("هٰذَا") == "هذا" and textprep.shadda_only("") == ""


def test_shadda_mode_returns_the_shadda_form_and_both_forms_beside_it(answers):
    queue, seen = answers
    queue.append(FULL)
    out = textprep.prepare_text("المعلم شد الحبل بقوة", "msa", normalize=False,
                                diacritize=True, marks="shadda")
    assert out["marks"] == "shadda"
    assert out["diacritized"] == out["text"] == SHADDA
    assert out["diacritized_full"] == FULL and out["diacritized_shadda"] == SHADDA
    assert out["letters_changed"] is False and len(seen) == 1     # one call serves both forms


def test_full_tashkeel_is_the_default_and_an_unknown_mode_falls_back_to_it(answers):
    queue, _ = answers
    queue.extend([FULL, FULL])
    plain = textprep.prepare_text("المعلم شد الحبل بقوة", "msa", normalize=False, diacritize=True)
    odd = textprep.prepare_text("المعلم شد الحبل بقوة", "msa", normalize=False,
                                diacritize=True, marks="everything")
    for out in (plain, odd):
        assert out["marks"] == "full" and out["diacritized"] == FULL
        assert out["diacritized_shadda"] == SHADDA


def test_the_letter_check_still_guards_shadda_mode(answers):
    queue, _ = answers
    queue.extend([REWORDED, REWORDED])
    out = textprep.prepare_text(ORIGINAL, "saudi", normalize=False, diacritize=True,
                                marks="shadda")
    assert out["letters_changed"] is True


def test_the_answer_names_the_provider_and_model(answers, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    answers[0].append(GOOD)
    out = textprep.prepare_text(ORIGINAL, "saudi", normalize=False, diacritize=True)
    assert out["provider"] == "groq" and out["model"] == "openai/gpt-oss-120b"


def test_the_prompt_asks_for_the_json_keys_json_mode_needs():
    assert "`diacritized`" in textprep._system_prompt("saudi", False, True).split("\n")[-1]
