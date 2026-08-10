#!/usr/bin/env python3
"""Call the TTS gateway's /api/{model}/synthesize from Python and keep the audio.

Synthesis is a two-step affair: the POST returns JSON describing the clip it wrote on
the server, and the wav itself is fetched afterwards from /audio/{model}/{filename}.

    python scripts/synthesize.py "مرحباً، كيف حالك؟" --voice abeer
    python scripts/synthesize.py "..." --voices          # list the built-in voices
    python scripts/synthesize.py "..." --model omnivoice_base --dialect saudi -o out.wav

httpx is the gateway's own dependency, so this runs in the arabic-tts-web env as is.
"""
import argparse
import pathlib
import sys

import httpx

BASE = "http://127.0.0.1:8025"
# Synthesis holds the model gate for the whole generation, so the read timeout is generous.
TIMEOUT = httpx.Timeout(connect=5.0, read=900.0, write=60.0, pool=5.0)


def voices(base=BASE, model="omnivoice_ft"):
    """The built-in voice ids the worker loaded — the same list the API console shows."""
    health = httpx.get(f"{base}/api/{model}/status", timeout=10.0).json()
    return health.get("voices", [])


def synthesize(text, model="omnivoice_ft", dialect="msa", voice="", gender="", age="",
               base=BASE):
    """POST the form and return the response JSON.

    Empty fields are dropped rather than sent blank: the worker applies its own defaults
    for anything absent, and an empty `voice` would otherwise read as "no cloning".
    """
    form = {"text": text, "dialect": dialect, "voice": voice, "gender": gender, "age": age}
    form = {k: v for k, v in form.items() if str(v).strip()}

    r = httpx.post(f"{base}/api/{model}/synthesize", data=form, timeout=TIMEOUT)
    r.raise_for_status()          # the gateway forwards the worker's status and message
    return r.json()


def download(result, dest, base=BASE):
    """Pull the generated wav named by a synthesize() result onto local disk."""
    r = httpx.get(f"{base}/audio/{result['model']}/{result['filename']}", timeout=TIMEOUT)
    r.raise_for_status()
    dest = pathlib.Path(dest)
    dest.write_bytes(r.content)
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="?", help="Arabic text to speak")
    ap.add_argument("--base", default=BASE, help=f"gateway URL (default {BASE})")
    ap.add_argument("--model", default="omnivoice_ft",
                    choices=["omnivoice_ft", "omnivoice_base"])
    ap.add_argument("--dialect", default="msa", choices=["msa", "saudi", "egyptian"])
    ap.add_argument("--voice", default="", help="built-in voice id; empty = the model's own")
    ap.add_argument("--gender", default="", choices=["", "male", "female"])
    ap.add_argument("--age", default="", choices=["", "young", "middle", "old"])
    ap.add_argument("-o", "--out", help="where to save the wav (default: the server's name)")
    ap.add_argument("--voices", action="store_true", help="list the built-in voices and exit")
    args = ap.parse_args()

    if args.voices:
        for v in voices(args.base, args.model):
            print(v)
        return 0
    if not args.text:
        ap.error("text is required (or pass --voices)")

    result = synthesize(args.text, model=args.model, dialect=args.dialect, voice=args.voice,
                        gender=args.gender, age=args.age, base=args.base)
    for key in ("filename", "model", "duration_s", "elapsed_s", "rtf", "sample_rate"):
        if key in result:
            print(f"{key:12} {result[key]}")
    print(f"{'model_input':12} {result.get('model_input', '')}")

    path = download(result, args.out or result["filename"], args.base)
    print(f"{'saved':12} {path.resolve()}  ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.HTTPStatusError as e:
        sys.exit(f"HTTP {e.response.status_code}: {e.response.text}")
    except httpx.RequestError as e:
        sys.exit(f"cannot reach the gateway at {e.request.url} — is start.sh running?")
