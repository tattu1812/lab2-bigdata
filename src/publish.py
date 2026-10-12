#!/usr/bin/env python3
"""Task 5 - công bố candidate vào research-release (chạy trong Pod publisher, s3-owner).

Thứ tự (không đảo):
  1. Chạy lại gate G01-G09 trên đúng bundle sẽ công bố -> phải PASS 9/9.
  2. Kiểm review độc lập: APPROVE, reviewer != tác giả curation, khớp run_id + hash candidate.
  3. Prefix release phải trống (không bao giờ ghi đè release cũ).
  4. Phát OpenLineage publish START.
  5. Upload từng object, tải lại và so SHA-256.
  6. Ghi release_manifest.json SAU CÙNG, tải lại và so SHA-256.
  7. Phát publish COMPLETE (tham chiếu hash manifest; manifest chỉ tham chiếu runId).
Bất kỳ bước nào hỏng: không ghi manifest, phát FAIL; consumer coi prefix không có manifest là chưa công bố.

Dùng: python3 publish.py --root <bundle> --run-id <curate_run> --release-id <id>
                         --review <review.json> --evidence-dir <dir mới> --operator <tên>
Exit: 0 PUBLISHED, 3 REFUSED, 4 FAILED.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate import run_gate, sha256_file  # noqa: E402

RELEASE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
BUCKET = os.environ.get("RELEASE_BUCKET", "research-release")
PREFIX = os.environ.get("RELEASE_PREFIX", "lab2/releases").strip("/")
CURATION_AUTHOR = os.environ.get("CURATION_AUTHOR", "Khánh")
PRODUCER = "https://github.com/tattu1812/lab2-bigdata/src/publish.py"
SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json#/definitions/RunEvent"


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(name):
    return " ".join(str(name or "").split()).casefold()


def s3_client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )


def check_review(review, run_id, candidate_sha):
    problems = []
    if review is None:
        return ["chưa có review.json"]
    if review.get("decision") != "APPROVE":
        problems.append(f"decision={review.get('decision')} (cần APPROVE)")
    reviewer = review.get("reviewer")
    if not norm(reviewer):
        problems.append("thiếu reviewer")
    if norm(reviewer) == norm(CURATION_AUTHOR) or norm(reviewer) == norm(review.get("curation_author")):
        problems.append("reviewer trùng tác giả curation")
    if not str(review.get("reason", "")).strip():
        problems.append("thiếu lý do")
    if review.get("run_id") != run_id:
        problems.append(f"review.run_id={review.get('run_id')} != {run_id}")
    if review.get("candidate_sha256") != candidate_sha:
        problems.append("review.candidate_sha256 khác hash candidate hiện tại")
    try:
        if review.get("reviewed_at", "") > now():
            problems.append(f"reviewed_at={review['reviewed_at']} nằm sau thời điểm publish")
        datetime.datetime.strptime(review["reviewed_at"], "%Y-%m-%dT%H:%M:%SZ")
    except (KeyError, TypeError, ValueError):
        problems.append("reviewed_at thiếu hoặc sai định dạng YYYY-MM-DDTHH:MM:SSZ")
    return problems


def lineage_event(event_type, run_uuid, release_id, run_id, outputs, facets=None):
    return {
        "eventType": event_type,
        "eventTime": now(),
        "run": {"runId": run_uuid, "facets": facets or {}},
        "job": {"namespace": "lab2-bigdata", "name": f"validate-and-publish-{release_id}", "facets": {}},
        "producer": PRODUCER,
        "schemaURL": SCHEMA_URL,
        "inputs": [
            {"namespace": "lab2-bigdata", "name": f"outputs/curate/{run_id}/candidate/curated.parquet"},
            {"namespace": "lab2-bigdata", "name": "catalog.json"},
        ],
        "outputs": outputs,
    }


def publish(root: Path, run_id: str, release_id: str, review_path, evidence_dir: Path,
            operator: str, s3=None):
    if not RELEASE_ID_RE.fullmatch(release_id):
        raise SystemExit(f"release_id không hợp lệ: {release_id}")
    if evidence_dir.exists():
        raise SystemExit(f"Thư mục evidence đã tồn tại: {evidence_dir}")
    evidence_dir.mkdir(parents=True)
    base_key = f"{PREFIX}/{release_id}"
    result = {"release_id": release_id, "curate_run_id": run_id, "operator": operator,
              "started_at": now(), "bucket": BUCKET, "prefix": base_key + "/",
              "s3_writes": 0, "steps": []}

    def finish(status, code, **extra):
        result.update(status=status, finished_at=now(), **extra)
        (evidence_dir / "publish-result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"PUBLISH: {status}" + (f" - {extra.get('reason')}" if extra.get("reason") else ""))
        return code

    # 1. Gate
    gate = run_gate(root, run_id)
    gate_path = evidence_dir / "gate-report.json"
    gate_path.write_text(json.dumps(gate, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    result["steps"].append({"step": "gate", "decision": gate["decision"], "passed": gate["passed"],
                            "failed_categories": gate["failed_categories"]})
    if gate["decision"] != "PASS":
        return finish("REFUSED", 3, reason=f"gate {gate['decision']} ({gate['passed']})")

    # 2. Review độc lập
    review = None
    if review_path and Path(review_path).exists():
        review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    problems = check_review(review, run_id, gate["candidate_sha256"])
    result["steps"].append({"step": "review", "problems": problems})
    if problems:
        return finish("REFUSED", 3, reason="review: " + "; ".join(problems))

    # 3. Không ghi đè
    s3 = s3 or s3_client()
    existing = s3.list_objects_v2(Bucket=BUCKET, Prefix=base_key + "/").get("KeyCount", 0)
    result["steps"].append({"step": "no_overwrite", "existing_objects": existing})
    if existing:
        return finish("REFUSED", 3, reason=f"prefix {base_key}/ đã có {existing} object")

    # 4. Lineage START
    run_uuid = str(uuid.uuid4())
    lineage_path = evidence_dir / "lineage-publish.jsonl"
    start = lineage_event("START", run_uuid, release_id, run_id, [])
    with lineage_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(start, ensure_ascii=False, separators=(",", ":")) + "\n")

    def emit(event):
        with lineage_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    review_copy = evidence_dir / "review.json"
    review_copy.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 5. Upload + verify. quarantine/duplicates KHÔNG vào release cho analyst.
    candidate = root / "outputs/curate" / run_id / "candidate/curated.parquet"
    files = [
        ("curated.parquet", candidate, "application/vnd.apache.parquet"),
        ("catalog.json", root / "catalog.json", "application/json"),
        ("gate-report.json", gate_path, "application/json"),
        ("review.json", review_copy, "application/json"),
    ]
    objects = []
    try:
        for name, path, ctype in files:
            key = f"{base_key}/{name}"
            body = path.read_bytes()
            s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=ctype)
            result["s3_writes"] += 1
            got = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
            sha, got_sha = hashlib.sha256(body).hexdigest(), hashlib.sha256(got).hexdigest()
            if sha != got_sha or len(got) != len(body):
                raise RuntimeError(f"verify sau upload sai: {key}")
            objects.append({"key": key, "bytes": len(body), "sha256": sha, "verified_after_upload": True})
    except Exception as exc:
        emit(lineage_event("FAIL", run_uuid, release_id, run_id, []))
        return finish("FAILED", 4, reason=f"{type(exc).__name__}: {exc}", objects=objects)

    # 6. Manifest ghi sau cùng
    review_sha = sha256_file(review_copy)
    by_check = {r["check"]: r["observed"] for r in gate["checks"]}
    manifest = {
        "manifest_version": "1.0",
        "release_id": release_id,
        "bucket": BUCKET,
        "prefix": base_key + "/",
        "created_at": now(),
        "publisher": operator,
        "curate_run_id": run_id,
        "publish_lineage": {"run_id": run_uuid, "start_event_time": start["eventTime"],
                            "note": "COMPLETE được phát sau manifest và tham chiếu hash manifest; "
                                    "manifest không chứa COMPLETE để tránh phụ thuộc vòng"},
        "candidate": {"key": f"{base_key}/curated.parquet", "sha256": gate["candidate_sha256"],
                      "row_count": by_check["G03"]["rows"],
                      "columns": [c for c, _ in by_check["G02"]["columns"]]},
        "gate": {"decision": gate["decision"], "passed": gate["passed"],
                 "gate_sha256": gate["gate_sha256"], "evaluated_at": gate["evaluated_at"],
                 "report_key": f"{base_key}/gate-report.json"},
        "review": {"reviewer": review["reviewer"], "decision": review["decision"],
                   "reason": review["reason"], "reviewed_at": review.get("reviewed_at"),
                   "review_sha256": review_sha, "report_key": f"{base_key}/review.json"},
        "objects": objects,
        "excluded_from_release": {
            "files": ["quarantine.csv", "duplicates.csv"],
            "reason": "sổ quarantine/duplicates chỉ nằm trong bản nộp hạn chế, không công bố cho analyst",
        },
    }
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    manifest_key = f"{base_key}/release_manifest.json"
    try:
        s3.put_object(Bucket=BUCKET, Key=manifest_key, Body=manifest_bytes, ContentType="application/json")
        result["s3_writes"] += 1
        got = s3.get_object(Bucket=BUCKET, Key=manifest_key)["Body"].read()
        if got != manifest_bytes:
            raise RuntimeError("manifest tải lại khác bản đã ghi")
    except Exception as exc:
        emit(lineage_event("FAIL", run_uuid, release_id, run_id, []))
        return finish("FAILED", 4, reason=f"{type(exc).__name__}: {exc}", objects=objects)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    (evidence_dir / "release_manifest.json").write_bytes(manifest_bytes)

    # 7. Lineage COMPLETE
    outputs = [{"namespace": f"s3://{BUCKET}", "name": o["key"],
                "facets": {"sha256": o["sha256"], "bytes": o["bytes"]}} for o in objects]
    outputs.append({"namespace": f"s3://{BUCKET}", "name": manifest_key,
                    "facets": {"sha256": manifest_sha, "bytes": len(manifest_bytes)}})
    emit(lineage_event("COMPLETE", run_uuid, release_id, run_id, outputs))
    return finish("PUBLISHED", 0, manifest_key=manifest_key, manifest_sha256=manifest_sha,
                  publish_run_id=run_uuid, objects=objects)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--release-id", required=True)
    ap.add_argument("--review", default=None)
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--operator", required=True)
    args = ap.parse_args()
    return publish(Path(args.root), args.run_id, args.release_id, args.review,
                   Path(args.evidence_dir), args.operator)


if __name__ == "__main__":
    sys.exit(main())
