#!/usr/bin/env python3
"""Kiểm tra chéo của Khánh (vai C) trên ca từ chối object bị sửa (I03) của Tú (vai A).

I03 gốc lật byte đầu tiên của observations_a.csv trong bộ nhớ. Ở đây sửa ở vị trí KHÁC,
trên bản sao dùng-một-lần trong thư mục tạm, rồi chạy chính src/check_integrity.py (I01 của
Tú) với HOME trỏ vào thư mục tạm đó. Ba ca:
  M1 – lật 1 bit ở byte giữa observations_b.jsonl (kích thước giữ nguyên, chỉ hash đổi)
  M2 – thay byte cuối sensors.csv bằng ký tự khác (kích thước giữ nguyên)
  M3 – nối thêm 1 byte vào qa_reference.csv (kích thước và hash cùng đổi)
Kỳ vọng mỗi ca: đúng object bị sửa FAIL / INPUT_INTEGRITY, 3 object còn lại PASS, I01 FAIL,
file gốc trong data/ không đổi hash.

Dùng (từ thư mục gốc repo):  python3 individual/C-khanh/i03_recheck.py
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/Lab2-datasets/input"
MANIFEST = ROOT / "data/trusted_manifest.json"
OUT = Path(__file__).with_name("i03-recheck.json")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def m1(b):
    b[len(b) // 2] ^= 0x01
    return f"lật bit thấp của byte offset {len(b) // 2}"


def m2(b):
    b[-1] = ord("X") if b[-1] != ord("X") else ord("Y")
    return f"thay byte cuối (offset {len(b) - 1})"


def m3(b):
    b.append(0x0A)
    return "nối thêm 1 byte '\\n' vào cuối file"


CASES = [("M1", "observations_b.jsonl", m1), ("M2", "sensors.csv", m2), ("M3", "qa_reference.csv", m3)]


def main():
    originals = {p.name: sha(p) for p in INPUT.iterdir() if p.is_file()}
    results = []
    for case, target, mutate in CASES:
        with tempfile.TemporaryDirectory() as home:
            repo = Path(home) / "lab2-bigdata"
            inp = repo / "data/Lab2-datasets/input"
            inp.mkdir(parents=True)
            for p in INPUT.iterdir():
                if p.is_file():
                    shutil.copy2(p, inp / p.name)
            shutil.copy2(MANIFEST, repo / "data/trusted_manifest.json")
            data = bytearray((inp / target).read_bytes())
            change = mutate(data)
            (inp / target).write_bytes(data)
            proc = subprocess.run(["python3", str(ROOT / "src/check_integrity.py")], capture_output=True,
                                  text=True, env={**os.environ, "HOME": home})
            report = json.loads((repo / "outputs/integrity-test.json").read_text(encoding="utf-8"))
        objs = {o["key"]: o for o in report["objects"]}
        ok = (report["status"] == "FAIL"
              and objs[target]["status"] == "FAIL" and objs[target]["reason"] == "INPUT_INTEGRITY"
              and all(o["status"] == "PASS" for k, o in objs.items() if k != target))
        results.append({
            "case": case, "target": target, "change": change,
            "expected": f"{target} FAIL/INPUT_INTEGRITY, 3 object khác PASS, I01 FAIL",
            "observed": {k: [o["status"], o["reason"]] for k, o in objs.items()},
            "observed_bytes": [objs[target]["expected_bytes"], objs[target]["actual_bytes"]],
            "i01_status": report["status"], "stdout": proc.stdout.strip().splitlines(),
            "status": "PASS" if ok else "FAIL",
        })

    after = {p.name: sha(p) for p in INPUT.iterdir() if p.is_file()}
    out = {
        "cross_check": "C (Khánh) → A (Tú): I03 trên bản sao khác, sửa byte ở vị trí khác",
        "checker_under_test": "src/check_integrity.py (I01 của Tú), sha256=" + sha(ROOT / "src/check_integrity.py"),
        "prediction": "Cả 3 ca: object bị sửa FAIL/INPUT_INTEGRITY, các object còn lại PASS; data/ không đổi.",
        "cases": results,
        "originals_unchanged": originals == after,
        "status": "PASS" if originals == after and all(r["status"] == "PASS" for r in results) else "FAIL",
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for r in results:
        print(f'{r["case"]} {r["target"]:22} {r["status"]}  ({r["change"]})')
    print("originals unchanged:", out["originals_unchanged"])
    print("I03 RECHECK:", out["status"])
    raise SystemExit(0 if out["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
