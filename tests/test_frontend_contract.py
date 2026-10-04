"""Contracts between the browser code and the Python it talks to.

app.js reproduces each worker's dialect/persona injection so the UI can preview the exact
string that reaches the model — several of its tables carry a "MUST match the worker map"
comment. Nothing enforces that at runtime: a drifted table just shows the user a preview
that quietly differs from what is synthesised. These tests are that enforcement.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import compose as compose_mod
import fish_server
import omnivoice_server
import server as gateway
import voxcpm2_server

STATIC = pathlib.Path(__file__).resolve().parent.parent / "static"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is required to evaluate the browser code")


def js_globals(filename, names):
    """Run a browser script under DOM stubs and return the named top-level constants.

    `const` declarations are lexical, so they never land on the context object — the
    reader is appended to the same script to capture them from inside that scope.

    i18n.js is prepended because both pages load it first and the catalogues below reach
    for its `t()` from label getters; without it every one of those getters throws.
    """
    path = STATIC / filename
    reader = "globalThis.__out = JSON.stringify({%s});" % ", ".join(names)
    driver = f"""
        const fs = require('fs'), vm = require('vm');
        const noop = () => {{}};
        const element = {{ addEventListener: noop, textContent: '', value: '', innerHTML: '',
                           className: '', hidden: false, dataset: {{}}, classList: {{
                             add: noop, remove: noop, toggle: noop, contains: () => false }},
                           querySelector: () => null, querySelectorAll: () => [],
                           appendChild: noop, closest: () => null, style: {{}} }};
        const ctx = {{
          document: {{ addEventListener: noop, getElementById: () => null,
                       querySelector: () => null, querySelectorAll: () => [],
                       createElement: () => element,
                       baseURI: 'http://localhost/', currentScript: null }},
          window: {{ location: {{ origin: 'http://localhost' }}, devicePixelRatio: 1 }},
          navigator: {{ clipboard: {{ writeText: noop }} }},
          localStorage: {{ getItem: () => null, setItem: noop, removeItem: noop }},
          setInterval: noop, setTimeout: noop, fetch: noop, console,
          URL, URLSearchParams,
        }};
        vm.createContext(ctx);
        vm.runInContext(fs.readFileSync({json.dumps(str(STATIC / "i18n.js"))}, 'utf8')
                        + fs.readFileSync({json.dumps(str(path))}, 'utf8')
                        + {json.dumps(reader)}, ctx);
        process.stdout.write(ctx.__out);
    """
    out = subprocess.run(["node", "-e", driver], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


APP = None


def app_js(*names):
    global APP
    if APP is None:
        APP = js_globals("app.js", ["MODELS", "DIALECTS", "GENDERS", "AGES", "JOBS",
                                    "DIALECT_LANG", "GENDER_EN", "AGE_EN"])
    return [APP[n] for n in names] if len(names) > 1 else APP[names[0]]


# ── Dialect injection ─────────────────────────────────────────
def test_fish_and_voxcpm2_agree_on_the_descriptors():
    assert fish_server._ARABIC_DIALECTS == voxcpm2_server._ARABIC_DIALECTS


def test_omnivoice_language_codes_match_the_worker():
    """OmniVoice takes the dialect as an ISO 639-3 code, never as instruct text."""
    assert app_js("DIALECT_LANG") == omnivoice_server._ARABIC_DIALECT_LANG


def test_the_ui_offers_exactly_the_dialects_every_layer_supports():
    ui = {d["id"] for d in app_js("DIALECTS")}
    assert ui == set(omnivoice_server._ARABIC_DIALECT_LANG)
    assert ui == set(compose_mod._DIALECTS)


# ── Persona injection ─────────────────────────────────────────
def test_gender_and_age_descriptors_match_every_worker():
    gender_en, age_en = app_js("GENDER_EN", "AGE_EN")
    for worker in (omnivoice_server, voxcpm2_server, fish_server):
        assert gender_en == worker._GENDERS, worker.__name__
        assert age_en == worker._AGES, worker.__name__


def test_persona_dropdowns_cover_the_worker_vocabulary_plus_auto():
    """The empty id is the UI's "let the model decide" — everything else must be known."""
    genders = {g["id"] for g in app_js("GENDERS")}
    ages = {a["id"] for a in app_js("AGES")}
    assert genders == {""} | set(omnivoice_server._GENDERS)
    assert ages == {""} | set(omnivoice_server._AGES)
    assert genders == set(compose_mod._GENDERS)
    assert ages == set(compose_mod._AGES)


# ── Agent presets ─────────────────────────────────────────────
def test_job_presets_match_the_compose_agent():
    assert [j["id"] for j in app_js("JOBS")] == list(compose_mod.JOBS)


# ── Model registry ────────────────────────────────────────────
def test_the_ui_models_are_routable_tts_workers():
    """Each interface model must resolve to a worker; `omnivoice` is a routing-only alias."""
    models = set(app_js("MODELS"))
    assert models <= set(gateway.TTS_WORKERS)
    assert set(gateway.TTS_WORKERS) - models == {"omnivoice"}


def test_each_interface_model_pins_a_worker_variant():
    """Every card hits the same worker, so the variant is the only thing telling them apart."""
    models = app_js("MODELS")
    for model, spec in models.items():
        assert gateway.MODEL_VARIANT.get(model), model
        assert spec["fixedParams"]["variant"] == gateway.MODEL_VARIANT[model], model
    assert len({gateway.TTS_WORKERS[m] for m in models}) == 1


def test_default_voices_match_the_worker():
    """A card's house voice must be the one the worker falls back to for its variant, or a
    curl call and the studio would clone different speakers for the same request."""
    specs = [spec for spec in app_js("MODELS").values() if spec.get("defaultVoice")]
    defaults = {spec["fixedParams"]["variant"]: spec["defaultVoice"] for spec in specs}
    assert defaults == omnivoice_server.VARIANT_DEFAULT_VOICES
    for voice in defaults.values():
        assert voice in omnivoice_server._VOICES, voice


def test_the_studio_knows_every_built_in_voice_before_the_first_fetch():
    """The picker starts from a static list; a built-in missing there would flash away,
    and one with other tags or in another place would jump between the picker's groups."""
    starting = js_globals("app.js", ["voiceCatalog"])["voiceCatalog"]
    built_in = [(k, v) for k, v in omnivoice_server._sorted_voices() if not v.get("custom")]
    assert [v["id"] for v in starting] == [k for k, _ in built_in]
    assert {v["id"]: v["tags"] for v in starting} == {k: v["tags"] for k, v in built_in}


def test_the_api_console_lists_the_same_built_in_voices():
    console = [v["id"] for v in js_globals("api.js", ["VOICES"])["VOICES"]]
    assert console == [k for k, v in omnivoice_server._sorted_voices() if not v.get("custom")]


def test_every_built_in_voice_and_tag_has_a_display_name():
    """An untranslated key would show up in the picker as `voice.joud` or `vtag.trained`."""
    shown = js_globals("app.js", [          # `key: expression` pairs of the object js_globals reads
        "labels: voiceCatalog.map(v => [v.id, voiceLabel(v)])",
        "tags: voiceCatalog.map(v => v.tags.map(k => [k, voiceTagLabel(k)]))",
        "groups: VOICE_GROUPS.map(g => t('voice.group.' + g))"])
    for vid, label in shown["labels"]:
        assert label and label != vid and not label.startswith("voice."), vid
    for key, label in (pair for voice in shown["tags"] for pair in voice):
        assert label and label != key, key
    assert all(g and not g.startswith("voice.group.") for g in shown["groups"])


def test_every_built_in_voice_says_how_the_najdi_model_knows_it():
    """The picker's groups hang on these two tags; a voice with neither would be mislabelled
    as cloned-only, and one with both would be a contradiction."""
    for vid, meta in omnivoice_server._VOICES.items():
        if not meta.get("custom"):
            assert len({"trained", "unseen"} & set(meta["tags"])) == 1, vid
            assert meta["gender"] in meta["tags"], vid


def test_every_built_in_voice_names_a_dialect_the_worker_can_send():
    """The studio sends no dialect, so a built-in voice's `language` is what it is spoken with;
    a code outside the worker's map would silently fall back to MSA."""
    for vid, meta in omnivoice_server._VOICES.items():
        if not meta.get("custom"):
            assert meta["language"] in omnivoice_server._ARABIC_DIALECT_LANG.values(), vid
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "dialect: ''" in script                       # nothing forces MSA over the voice


def test_the_marks_switch_offers_exactly_the_modes_the_agent_knows():
    """Full tashkeel or shadda only: a button for a mode textprep does not know would
    silently get full tashkeel back."""
    import textprep
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    offered = set(re.findall(r'id="tk-marks-(\w+)"', page))
    assert offered == set(textprep.MARK_MODES)
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "marks: tashkeelMarks" in script                 # the choice reaches /api/prepare
    for key in ("diacritized_full", "diacritized_shadda"):  # both forms are kept for switching
        assert key in script, key


def test_transcription_is_not_a_synthesis_model():
    """Mixing the ASR worker into MODELS would put it in the compare grid and synth flow."""
    assert "transcribe" not in app_js("MODELS")
    assert "transcribe" in gateway.WORKER_URLS and "transcribe" in gateway.OUTPUT_DIRS
    assert "transcribe" not in gateway.TTS_WORKERS


def test_every_model_has_an_output_directory():
    for model in app_js("MODELS"):
        assert model in gateway.OUTPUT_DIRS


# ── API console ───────────────────────────────────────────────
def gateway_routes():
    return {(method, route.path)
            for route in gateway.app.routes
            for method in getattr(route, "methods", ())}


def test_every_documented_endpoint_exists_on_the_gateway():
    """The console is the public contract — a stale entry hands users a 404."""
    for spec in js_globals("api.js", ["ENDPOINTS"])["ENDPOINTS"]:
        assert (spec["method"], spec["path"]) in gateway_routes(), spec["path"]


def test_documented_path_parameters_are_real_route_parameters():
    for spec in js_globals("api.js", ["ENDPOINTS"])["ENDPOINTS"]:
        declared = {f["name"] for f in spec["fields"] if f.get("in") == "path"}
        assert declared == set(re.findall(r"\{(\w+)\}", spec["path"])), spec["path"]


def test_documented_model_options_are_routable():
    for spec in js_globals("api.js", ["ENDPOINTS"])["ENDPOINTS"]:
        for field in spec["fields"]:
            if field["name"] != "model" or field.get("in") != "path":
                continue
            known = set(gateway.TTS_WORKERS) if spec["path"].endswith("/synthesize") \
                else set(gateway.OUTPUT_DIRS) | set(gateway.WORKER_URLS)
            assert set(field["options"]) <= known, spec["path"]


# ── Page wiring ───────────────────────────────────────────────
def init_body():
    """The source of app.js's init(), which runs against the static page on load."""
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    body = re.search(r"\nfunction init\(\) \{\n(.*?)\n\}\n", source, re.S)
    assert body, "init() not found — the extraction pattern went stale"
    return body.group(1)


def test_every_element_init_binds_to_exists_in_the_page():
    """init() throws on the first missing id, which would blank the whole studio."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    bound = set(re.findall(r"\$\('([\w-]+)'\)", init_body()))
    assert bound, "no bindings found — the extraction pattern went stale"

    missing = [i for i in bound if f'id="{i}"' not in html]
    assert not missing, f"init() reaches for ids absent from index.html: {sorted(missing)}"


def test_ids_bound_after_render_are_ones_app_js_actually_generates():
    """Handlers attached outside init() target markup the renderers inject — not the page."""
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    bound = set(re.findall(r"\$\('([\w-]+)'\)\.addEventListener", source))
    generated = set(re.findall(r'id="([\w-]+)"', source))

    unreachable = [i for i in bound if f'id="{i}"' not in html and i not in generated]
    assert not unreachable, f"app.js binds to ids nothing ever creates: {sorted(unreachable)}"


def test_the_main_flow_is_never_folded_away():
    """Text, voice and Generate are what the studio opens on. The optional panels are folded
    <details>, each with the id its open/closed state is remembered under."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    folded = re.findall(r'<details class="panel-section tool"(?: id="([\w-]+)")?>(.*?)</details>', html, re.S)
    assert folded, "no folded tools found — the extraction pattern went stale"
    ids = [tool_id for tool_id, _ in folded]
    assert all(ids) and len(set(ids)) == len(ids), ids
    inside = "".join(body for _, body in folded)
    for primary in ("text-input", "voice-list", "btn-synth"):
        assert f'id="{primary}"' in html and f'id="{primary}"' not in inside, primary
    for optional in ("model-cards", "btn-compare", "transcribe-zone"):
        assert f'id="{optional}"' in inside, optional


def test_the_api_console_page_loads_its_own_assets():
    html = (STATIC / "api.html").read_text(encoding="utf-8")
    for asset in ("style.css", "api.css", "api.js"):
        assert asset in html
        assert (STATIC / asset).exists()


def test_the_log_console_page_loads_its_own_assets():
    html = (STATIC / "logs.html").read_text(encoding="utf-8")
    for asset in ("style.css", "logs.css", "logs.js", "i18n.js"):
        assert asset in html
        assert (STATIC / asset).exists()


def test_the_log_console_binds_only_to_ids_its_page_declares():
    """logs.js reaches for page elements everywhere, not just in init() — all must exist."""
    html = (STATIC / "logs.html").read_text(encoding="utf-8")
    bound = set(re.findall(r"\$\('([\w-]+)'\)", (STATIC / "logs.js").read_text(encoding="utf-8")))
    assert bound, "no bindings found — the extraction pattern went stale"

    missing = [i for i in bound if f'id="{i}"' not in html]
    assert not missing, f"logs.js reaches for ids absent from logs.html: {sorted(missing)}"


@pytest.mark.parametrize("page,links", [
    ("index.html", ("api.html", "logs.html")),
    ("api.html",   ("index.html", "logs.html")),
    ("logs.html",  ("index.html", "api.html")),
])
def test_every_page_links_to_the_other_two(page, links):
    html = (STATIC / page).read_text(encoding="utf-8")
    for target in links:
        assert f'href="{target}"' in html, f"{page} does not link to {target}"
