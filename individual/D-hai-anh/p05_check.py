#!/usr/bin/env python3
"""Kiểm tra chéo của Hải Anh (vai D) trên ca gate thiếu metadata (P05) của Trung (vai E).

Chạy trong Pod publisher. Sao chép bundle gốc (do run_task5.sh dựng) sang thư mục riêng,
sửa catalog.json của bản sao rồi chạy src/gate.py của Trung:
  CTRL – không sửa                                  → kỳ vọng PASS 9/9
  P05  – xóa steward của curated_candidate           → kỳ vọng REJECT, METADATA trong danh sách FAIL
  P05b – steward = "   " (chỉ khoảng trắng)         → kỳ vọng REJECT, METADATA (chuỗi rỗng = thiếu)
Bundle gốc không bị sửa (so digest trước/sau).

  python3 p05_check.py --base /work/bundles/<id> --gate /work/task5/gate.py \
      --run-id task3-20261012-01 --work /work/xcheck-D --out /work/xcheck-D/p05-check.json
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def digest(root):
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def drop_steward(ds):
    ds.pop("steward")


def blank_steward(ds):
    ds["steward"] = "   "


CASES = [("CTRL", None, "PASS", None),
         ("P05", drop_steward, "REJECT", "METADATA"),
         ("P05b", blank_steward, "REJECT", "METADATA")]


def main():
    ap = argparse.ArgumentParser()
    for a in ("--base", "--gate", "--run-id", "--work", "--out"):
        ap.add_argument(a, required=True)
    args = ap.parse_args()
    base, work = Path(args.base), Path(args.work)
    before = digest(base)
    results = []
    for case, mutate, exp_decision, exp_cat in CASES:
        root = work / case
        if root.exists():
            raise SystemExit(f"Đã tồn tại: {root}")
        shutil.copytree(base, root)
        if mutate:
            path = root / "catalog.json"
            cat = json.loads(path.read_text(encoding="utf-8"))
            mutate(next(d for d in cat["datasets"] if d["dataset_id"] == "curated_candidate"))
            path.write_text(json.dumps(cat, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report_path = root / "gate-report.json"
        proc = subprocess.run(["python3", args.gate, "--root", str(root), "--run-id", args.run_id,
                               "--out", str(report_path)], capture_output=True, text=True)
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        failed = [c["category"] for c in rep["checks"] if c["status"] != "PASS"]
        g07 = next(c for c in rep["checks"] if c["category"] == "METADATA")
        ok = rep["decision"] == exp_decision and (exp_cat is None and not failed or exp_cat in failed)
        results.append({"case": case, "expected": f"{exp_decision}" + (f" / {exp_cat}" if exp_cat else " 9/9"),
                        "decision": rep["decision"], "passed": rep["passed"], "failed_categories": failed,
                        "metadata_reasons": g07.get("reasons"), "exit_code": proc.returncode,
                        "status": "PASS" if ok else "FAIL"})
    after = digest(base)
    out = {"cross_check": "D (Hải Anh) → E (Trung): gate phải REJECT khi thiếu steward",
           "prediction": "CTRL PASS 9/9; P05 và P05b REJECT với METADATA, 8/9 (chỉ G07 FAIL).",
           "gate_sha256": hashlib.sha256(Path(args.gate).read_bytes()).hexdigest(),
           "cases": results, "base_bundle_unchanged": before == after,
           "status": "PASS" if before == after and all(r["status"] == "PASS" for r in results) else "FAIL"}
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for r in results:
        print(f'{r["case"]:5} {r["decision"]:7} {r["passed"]} failed={r["failed_categories"]} -> {r["status"]}')
    print("P05 CROSSCHECK:", out["status"])
    raise SystemExit(0 if out["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
