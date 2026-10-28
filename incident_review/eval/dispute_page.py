# incident_review/eval/dispute_page.py
"""HTML page of every (image, rule) where the dataset label and the reviewer disagree,
for a human to adjudicate. Writes <data>/dispute/{index.html,items.json,img/}."""
import argparse
import html
import json
import shutil
from pathlib import Path

RULE_KO = {"PPE-HARDHAT": "안전모", "PPE-VEST": "안전조끼"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    args = ap.parse_args()
    d = args.data
    labels = {r["id"]: r for r in json.loads((d / "labels.json").read_text())}
    claims = {c["id"]: c["rules"] for c in map(json.loads, (d / "stage1_claims.jsonl").read_text().splitlines())}
    base = {b["id"]: b["text"] for b in map(json.loads, (d / "baseline.jsonl").read_text().splitlines())}

    items = []
    for r in map(json.loads, (d / "review.jsonl").read_text().splitlines()):
        if "error" in r:
            continue
        for rid in claims[r["id"]]:
            label = labels[r["id"]]["labels"].get(rid)
            check = r["review"]["checks"][rid]
            if (label == "NOT_VIOLATED" and check["result"] == "VIOLATED") or (
                label == "VIOLATED" and check["result"] != "VIOLATED"
            ):
                items.append({"id": r["id"], "rule": rid, "label": label, "review": check["result"],
                              "observation": check["observation"], "stage1": base[r["id"]]})

    out = d / "dispute"
    (out / "img").mkdir(parents=True, exist_ok=True)
    cards = []
    for n, it in enumerate(items, 1):
        it["n"] = n
        shutil.copy(d / labels[it["id"]]["path"], out / "img" / f"{n:02d}.jpg")
        label_ko = "위반" if it["label"] == "VIOLATED" else "정상"
        cards.append(
            f"<div class=c><h3>{n}. {RULE_KO[it['rule']]}</h3><img src='img/{n:02d}.jpg'>"
            f"<p><b>데이터셋 라벨:</b> {label_ko}<br><b>재검토:</b> {it['review']}<br>{html.escape(it['observation'])}"
            f"<br><small>1차: {html.escape(it['stage1'])}</small></p></div>"
        )
    (out / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))
    (out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>똑띠 v2 검수</title><style>body{font-family:sans-serif;margin:16px;background:#fafafa;color:#222}"
        ".c{background:#fff;border:1px solid #ddd;padding:12px;margin:12px 0;max-width:760px}"
        "img{max-width:100%;max-height:420px}</style>"
        f"<h1>라벨과 재검토가 엇갈린 {len(items)}건</h1>"
        "<p>해당 규칙이 실제로 <b>위반 / 정상 / 현장 아님(건설현장 작업자가 아님) / 판단 불가</b> 중 무엇인지 골라 주세요.</p>"
        + "".join(cards)
    )
    print(len(items), "items ->", out / "index.html")


if __name__ == "__main__":
    main()
