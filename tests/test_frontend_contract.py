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
    """Both cards hit the same worker, so the variant is the only thing telling them apart."""
    for model in app_js("MODELS"):
        assert gateway.MODEL_VARIANT.get(model), model
    assert len({gateway.TTS_WORKERS[m] for m in app_js("MODELS")}) == 1


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
