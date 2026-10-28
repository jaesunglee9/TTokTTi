# incident_review/eval/build_labels.py
"""Turn the CC BY 4.0 'Construction Site Safety' COCO export into per-rule labels.

The dataset merges several Roboflow projects, so many images annotate only
vehicles or only people. A rule gets a label only when the image annotates that
PPE at all: no-hardhat -> VIOLATED, hardhat without no-hardhat -> NOT_VIOLATED,
neither -> None (not judgeable, excluded from scoring).
"""
import argparse
import collections
import json
from pathlib import Path

SPLITS = ["train", "valid", "test"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True, help="dir containing raw/{train,valid,test}")
    args = ap.parse_args()

    rows = []
    for split in SPLITS:
        coco = json.loads((args.data / "raw" / split / "_annotations.coco.json").read_text())
        names = {c["id"]: c["name"] for c in coco["categories"]}
        counts = collections.defaultdict(collections.Counter)
        for a in coco["annotations"]:
            counts[a["image_id"]][names[a["category_id"]]] += 1
        for im in coco["images"]:
            c = counts[im["id"]]
            labels = {
                "PPE-HARDHAT": "VIOLATED" if c["no-hardhat"] else ("NOT_VIOLATED" if c["hardhat"] else None),
                "PPE-VEST": "VIOLATED" if c["no-safety vest"] else ("NOT_VIOLATED" if c["safety vest"] else None),
            }
            if all(v is None for v in labels.values()):
                continue
            rows.append({
                "id": f"{split}/{im['file_name']}",
                "path": f"raw/{split}/{im['file_name']}",
                "labels": labels,
                "annotations": dict(c),
            })

    (args.data / "labels.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    tally = collections.Counter((k, v) for r in rows for k, v in r["labels"].items())
    print(f"{len(rows)} images", dict(tally))


if __name__ == "__main__":
    main()
