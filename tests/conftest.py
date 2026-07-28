"""Shared fixtures.

Nothing here talks to a GPU, an OpenAI key or a real model: the heavy imports
(`transformers`, `voxcpm`, `omnivoice`, `langchain_openai`) are swapped for fakes in
`sys.modules` before the code under test reaches its lazy `import`, and the gateway's
httpx client is swapped for a scripted transport. That keeps the suite runnable in the
gateway env alone, which is the only env every machine has.
"""
import importlib
import pathlib
import sys
import types

import numpy as np
import pytest
import soundfile as sf

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "workers"))   # workers run as scripts; `from _common import ...`


# ── Audio helpers ─────────────────────────────────────────────
def write_wav(path, seconds=0.5, rate=16_000):
    """A real (silent) wav — the workers call soundfile on these, so they must be valid."""
    sf.write(str(path), np.zeros(int(seconds * rate), dtype=np.float32), rate)
    return path


@pytest.fixture
def wav_file(tmp_path):
    return write_wav(tmp_path / "sample.wav")


@pytest.fixture
def upload(wav_file):
    """A ready-made multipart file tuple, re-openable per request."""
    def _make(name="sample.wav", field="audio"):
        return {field: (name, wav_file.open("rb"), "audio/wav")}
    return _make


# ── Module loading ────────────────────────────────────────────
def fresh_import(name, monkeypatch, env):
    """Import a module with `env` applied, discarding any cached copy.

    Workers and the gateway read their config into module-level constants at import
    time, so every test that needs different paths must re-import rather than reload.
    """
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module(name)
    monkeypatch.setitem(sys.modules, name, module)
    return module


# ── Fake ML stacks ────────────────────────────────────────────
class Recorder(dict):
    """Records the kwargs each faked call received so tests can assert on them."""


class FakeBatch(dict):
    """Stands in for transformers' BatchFeature: dict-like, with a chainable .to().

    The move is recorded on an attribute, never as a key — anything left in the mapping
    would be splatted into generate(**inputs) and mask the very bug these tests guard.
    """
    moved_to = None

    def to(self, *args, **kwargs):
        self.moved_to = (args, kwargs)
        return self


@pytest.fixture
def fake_transformers(monkeypatch):
    """Install a fake `transformers` + `transformers.audio_utils`.

    Returns the recorder dict; tests tweak `rec['chunks']` to force the long-form path
    and read back the kwargs that reached the processor / generate / decode.
    """
    rec = Recorder(chunks=None, transcript="  مرحباً بالعالم  ", decode_error=None,
                   load_error=None, samples=np.zeros(8_000, dtype=np.float32))

    class FakeProcessor:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            rec["processor_from_pretrained"] = (model_id, kwargs)
            return cls()

        def __call__(self, audio, **kwargs):
            rec["processor_kwargs"] = kwargs
            rec["audio_len"] = len(audio)
            batch = FakeBatch(input_features="FEATURES")
            if rec["chunks"] is not None:
                batch["audio_chunk_index"] = rec["chunks"]
            rec["batch"] = batch
            return batch

        def decode(self, outputs, **kwargs):
            if rec["decode_error"]:
                raise RuntimeError(rec["decode_error"])
            rec["decode_kwargs"] = kwargs
            rec["decoded"] = outputs
            return rec["transcript"]

    class FakeModel:
        device = "cpu"
        dtype = "float32"

        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            rec["model_from_pretrained"] = (model_id, kwargs)
            return cls()

        def eval(self):
            rec["eval_called"] = True
            return self

        def generate(self, **kwargs):
            rec["generate_kwargs"] = kwargs
            return ["TOKEN_IDS"]

    transformers = types.ModuleType("transformers")
    transformers.AutoProcessor = FakeProcessor
    transformers.CohereAsrForConditionalGeneration = FakeModel

    audio_utils = types.ModuleType("transformers.audio_utils")

    def load_audio(path, sampling_rate=16_000):
        if rec["load_error"]:
            raise RuntimeError(rec["load_error"])
        rec["load_audio"] = (pathlib.Path(path).suffix, sampling_rate)
        return rec["samples"]

    audio_utils.load_audio = load_audio
    transformers.audio_utils = audio_utils

    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setitem(sys.modules, "transformers.audio_utils", audio_utils)
    return rec


@pytest.fixture
def fake_omnivoice(monkeypatch):
    rec = Recorder(error=None, audio=[np.zeros(24_000, dtype=np.float32)])

    class OmniVoice:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            rec["from_pretrained"] = (model_id, kwargs)
            return cls()

        def generate(self, **kwargs):
            rec["generate_kwargs"] = kwargs
            if rec["error"]:
                raise RuntimeError(rec["error"])
            return rec["audio"]

    module = types.ModuleType("omnivoice")
    module.OmniVoice = OmniVoice
    monkeypatch.setitem(sys.modules, "omnivoice", module)
    return rec


@pytest.fixture
def fake_voxcpm(monkeypatch):
    rec = Recorder(error=None, sample_rate=48_000, wav=np.zeros(48_000, dtype=np.float32))

    class TTSModel:
        def __init__(self, rate):
            self.sample_rate = rate

    class VoxCPM:
        def __init__(self):
            self.tts_model = TTSModel(rec["sample_rate"])

        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            rec["from_pretrained"] = (model_id, kwargs)
            return cls()

        def generate(self, **kwargs):
            rec["generate_kwargs"] = kwargs
            if rec["error"]:
                raise RuntimeError(rec["error"])
            return rec["wav"]

    module = types.ModuleType("voxcpm")
    module.VoxCPM = VoxCPM
    monkeypatch.setitem(sys.modules, "voxcpm", module)
    return rec


@pytest.fixture
def fake_llm(monkeypatch):
    """Fake `langchain_openai.ChatOpenAI` whose structured output is set per test."""
    rec = Recorder(result=None, error=None)

    class Structured:
        def invoke(self, messages):
            rec["messages"] = messages
            if rec["error"]:
                raise rec["error"]
            return rec["result"]

    class ChatOpenAI:
        def __init__(self, **kwargs):
            rec["init_kwargs"] = kwargs

        def with_structured_output(self, schema):
            rec["schema"] = schema
            return Structured()

    module = types.ModuleType("langchain_openai")
    module.ChatOpenAI = ChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", module)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    return rec
