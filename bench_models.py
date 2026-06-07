#!/usr/bin/env python3
"""Benchmark all free OpenRouter models for landscape/morris script quality."""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from ffmpeg_ai.ai.openrouter import (  # noqa: E402
    FREE_MODELS, _generate_landscape_script, get_client, _count_words,
)

TOPIC = "the pharmacology of ibogaine and its use in opioid addiction treatment"
DURATION = 180  # 3 min test — enough to see prose quality without long waits
STYLE = "morris"


async def bench_model(model: str, client) -> dict:
    t0 = time.monotonic()
    try:
        result = await _generate_landscape_script(
            TOPIC, duration=DURATION, model=model, style=STYLE, client=client
        )
        elapsed = time.monotonic() - t0
        if result is None:
            return {"model": model, "ok": False, "error": "null response", "elapsed": elapsed}
        wc = _count_words(result)
        min_w = result.get("_min_words", 0)
        n_seg = len(result.get("segments", []))
        title = result.get("title", "")
        hook = result.get("hook", {}).get("text", "")[:120]
        return {
            "model": model,
            "ok": True,
            "elapsed": elapsed,
            "words": wc,
            "min_words": min_w,
            "passed_min": wc >= min_w,
            "segments": n_seg,
            "title": title,
            "hook_preview": hook,
        }
    except Exception as e:
        elapsed = time.monotonic() - t0
        return {"model": model, "ok": False, "error": str(e)[:120], "elapsed": elapsed}


async def main():
    client = get_client()
    results = []
    for model in FREE_MODELS:
        print(f"\ntesting {model} ...", flush=True)
        r = await bench_model(model, client)
        results.append(r)
        if r["ok"]:
            flag = "PASS" if r["passed_min"] else "SHORT"
            wc, mw, seg = r["words"], r["min_words"], r["segments"]
            print(f"  [{flag}] {r['elapsed']:.1f}s  words={wc}/{mw}  segs={seg}")
            print(f"  title: {r['title']}")
            print(f"  hook:  {r['hook_preview']}")
        else:
            print(f"  [FAIL] {r['elapsed']:.1f}s  {r['error']}")

    print("\n\n=== SUMMARY ===")
    print(f"{'model':<55} {'ok':>4} {'elapsed':>8} {'words':>7} {'pass':>5} {'segs':>5}")
    print("-" * 85)
    for r in results:
        if r["ok"]:
            print(
                f"{r['model']:<55} {'yes':>4} {r['elapsed']:>7.1f}s"
                f" {r['words']:>7} {'yes' if r['passed_min'] else 'no':>5} {r['segments']:>5}"
            )
        else:
            print(f"{r['model']:<55} {'no':>4} {r['elapsed']:>7.1f}s  {r['error'][:25]}")

    out = Path("/tmp/bench_models.json")
    out.write_text(json.dumps(results, indent=2))
    print(f"\nfull results → {out}")


if __name__ == "__main__":
    asyncio.run(main())
