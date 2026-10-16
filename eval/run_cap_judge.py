"""Week 12 — run the integrated-system judge over the natural cases and the planted set.

    python eval/run_cap_judge.py --version v1 --split dev --out eval/cap_judge_v1_dev.json
    python eval/run_cap_judge.py --version v1 --split test --runs 3 --out eval/cap_judge_v1_test.json

Judge calls are checkpointed per case, so a quota stop loses nothing. Provider errors are recorded as ERROR and
excluded from agreement (never scored as UNGROUNDED, which would look like a system failure).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

import cap_judge as cj                                   # noqa: E402
from src import llm                                      # noqa: E402

SYSTEM = ("You are a careful, sceptical auditor. You answer in the exact format requested and nothing more.")
VERDICT = re.compile(r"VERDICT\s*:\s*(GROUNDED|UNGROUNDED)", re.I)
WHY = re.compile(r"WHY\s*:\s*(.+)", re.I | re.S)


def render(template: str, case: dict) -> str:
    return template.format(passages=cj.render_passages(case), tool_results=cj.render_tool_results(case),
                           claim_file=case["claim_file"], prose=cj.render_prose(case))


def planted_case(spec: dict, runs: dict, chunks: dict) -> dict:
    v, c = spec["base"].split(":")
    case = cj.build_case(runs[(v, c)], chunks)
    pr = case["prose"]
    if spec["field"] == "summary":
        pr["summary"] = spec["edited_text"]
    elif spec["field"] == "referral_reason":
        pr["referral_reason"] = spec["edited_text"]
    else:
        pr["why"][int(spec["field"].split(":")[1])] = spec["edited_text"]
    return case


def judge_once(prompt: str, model: str) -> dict:
    t0 = time.time()
    try:
        raw = llm.chat(SYSTEM, prompt, provider="gemini", model=model)
    except Exception as exc:                                    # noqa: BLE001
        return {"verdict": "ERROR", "why": "", "error": str(exc)[:200], "seconds": round(time.time() - t0, 1)}
    m = VERDICT.search(raw)
    w = WHY.search(raw)
    return {"verdict": m.group(1).upper() if m else "ERROR",
            "why": (w.group(1).strip().split("\n")[0] if w else raw.strip()[:200]),
            "error": "" if m else "no VERDICT line", "seconds": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v1")
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    template, psha = cj.load_prompt(a.version)
    labels = json.loads((ROOT / "eval" / "labels_cap_70.json").read_text())["labels"]
    planted = json.loads((ROOT / "eval" / "planted_cap.json").read_text())
    runs, chunks = cj.load_runs(), cj._chunk_store()

    todo = [("natural", k, v["split"], None) for k, v in labels.items()]
    todo += [("planted", p["id"], p["split"], p) for p in planted]
    todo = [t for t in todo if a.split == "all" or t[2] == a.split]

    out_path = Path(a.out)
    results = json.loads(out_path.read_text()) if out_path.exists() else {}
    for kind, key, split, spec in todo:
        rid = f"{kind}:{key}"
        have = results.get(rid, {}).get("runs", [])
        if len(have) >= a.runs and all(r["verdict"] != "ERROR" for r in have):
            continue
        if kind == "natural":
            v, c = key.split(":")
            case = cj.build_case(runs[(v, c)], chunks)
        else:
            case = planted_case(spec, runs, chunks)
        prompt = render(template, case)
        have = [r for r in have if r["verdict"] != "ERROR"]
        while len(have) < a.runs:
            have.append(judge_once(prompt, a.model))
        results[rid] = {"kind": kind, "key": key, "split": split, "runs": have}
        out_path.write_text(json.dumps({**results}, indent=1))
        print(f"{rid:<34} {[r['verdict'][:1] for r in have]}", flush=True)
    meta = {"judge_prompt": a.version, "prompt_sha": psha, "model": a.model,
            "written_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    results["_meta"] = meta
    out_path.write_text(json.dumps(results, indent=1))
    print("done", meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
