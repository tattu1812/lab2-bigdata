#!/usr/bin/env python3
"""Task 5 - kiểm tra phía analyst (chạy trong Pod consumer, s3-analyst).

  1. GET release_manifest.json + từng object -> SHA-256/bytes khớp manifest.
  2. Manifest là object ghi sau cùng (LastModified >= mọi object khác).
  3. Đếm dòng curated.parquet = manifest.candidate.row_count; không có sổ quarantine/duplicates.
  4. GET raw (research-raw) phải bị từ chối 403.
  5. Các release của ca bị REJECT không có manifest (và không có object nào).

Dùng: python3 consumer_check.py --release-id <id> --rejected <id-P02,...> --out <consumer-check.json>
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import boto3
import duckdb
from botocore.exceptions import ClientError

BUCKET = os.environ.get("RELEASE_BUCKET", "research-release")
PREFIX = os.environ.get("RELEASE_PREFIX", "lab2/releases").strip("/")
RAW_BUCKET = os.environ.get("RAW_BUCKET", "research-raw")
RAW_KEY = os.environ.get("RAW_PROBE_KEY", "lab2/inputs/batch-01/sensors.csv")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-id", required=True)
    ap.add_argument("--rejected", default="", help="danh sách release_id bị REJECT, cách nhau bằng dấu phẩy")
    ap.add_argument("--operator", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )
    principal = os.environ.get("PRINCIPAL", "?")
    checks = {}
    base = f"{PREFIX}/{args.release_id}"

    # 1. Manifest + objects
    manifest_key = f"{base}/release_manifest.json"
    head_manifest = s3.head_object(Bucket=BUCKET, Key=manifest_key)
    manifest = json.loads(s3.get_object(Bucket=BUCKET, Key=manifest_key)["Body"].read())
    objects, tmp = [], Path(tempfile.mkdtemp(prefix="consumer-"))
    for obj in manifest["objects"]:
        body = s3.get_object(Bucket=BUCKET, Key=obj["key"])["Body"].read()
        head = s3.head_object(Bucket=BUCKET, Key=obj["key"])
        sha = hashlib.sha256(body).hexdigest()
        objects.append({"key": obj["key"], "bytes": len(body), "sha256": sha,
                        "match": sha == obj["sha256"] and len(body) == obj["bytes"],
                        "last_modified": head["LastModified"].isoformat()})
        if obj["key"].endswith(".parquet"):
            (tmp / "curated.parquet").write_bytes(body)
    checks["hash_match"] = {
        "status": "PASS" if objects and all(o["match"] for o in objects) else "FAIL",
        "matched": f"{sum(o['match'] for o in objects)}/{len(objects)}",
        "objects": objects,
    }

    # 2. Manifest ghi sau cùng
    manifest_time = head_manifest["LastModified"]
    latest_other = max(s3.head_object(Bucket=BUCKET, Key=o["key"])["LastModified"] for o in manifest["objects"])
    listed = s3.list_objects_v2(Bucket=BUCKET, Prefix=base + "/").get("Contents", [])
    checks["manifest_written_last"] = {
        "status": "PASS" if manifest_time >= latest_other else "FAIL",
        "manifest_last_modified": manifest_time.isoformat(),
        "latest_object_last_modified": latest_other.isoformat(),
        "listed_keys": sorted(o["Key"] for o in listed),
        "unlisted_in_manifest": sorted({o["Key"] for o in listed} - {o["key"] for o in manifest["objects"]} - {manifest_key}),
    }

    # 3. Đọc candidate, đếm dòng, không có sổ hạn chế
    con = duckdb.connect()
    rows = con.execute(f"SELECT count(*) FROM read_parquet('{tmp / 'curated.parquet'}')").fetchone()[0]
    distinct = con.execute(f"SELECT count(DISTINCT record_id) FROM read_parquet('{tmp / 'curated.parquet'}')").fetchone()[0]
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{tmp / 'curated.parquet'}')").fetchall()]
    con.close()
    restricted_present = [k for k in checks["manifest_written_last"]["listed_keys"]
                          if k.endswith(("quarantine.csv", "duplicates.csv"))]
    checks["row_count"] = {
        "status": "PASS" if rows == manifest["candidate"]["row_count"] == distinct and not restricted_present else "FAIL",
        "rows": rows, "distinct_record_id": distinct,
        "manifest_row_count": manifest["candidate"]["row_count"],
        "columns": cols, "restricted_ledgers_in_release": restricted_present,
    }

    # 4. Raw phải bị chặn
    try:
        s3.get_object(Bucket=RAW_BUCKET, Key=RAW_KEY)
        checks["raw_denied"] = {"status": "FAIL", "detail": "analyst đọc được raw"}
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        http = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        checks["raw_denied"] = {"status": "PASS" if http == 403 else "FAIL",
                                "key": f"s3://{RAW_BUCKET}/{RAW_KEY}", "error": code, "http_status": http}

    # 5. Ca bị REJECT không có manifest
    rejected = []
    for rel in [r for r in args.rejected.split(",") if r]:
        key = f"{PREFIX}/{rel}/release_manifest.json"
        try:
            s3.head_object(Bucket=BUCKET, Key=key)
            has_manifest, http = True, 200
        except ClientError as exc:
            has_manifest = False
            http = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        n = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{PREFIX}/{rel}/").get("KeyCount", 0)
        rejected.append({"release_id": rel, "manifest_present": has_manifest, "head_http_status": http,
                         "objects_under_prefix": n})
    checks["rejected_have_no_manifest"] = {
        "status": "PASS" if rejected and all(not r["manifest_present"] and r["objects_under_prefix"] == 0
                                             for r in rejected) else "FAIL",
        "count": len(rejected), "cases": rejected,
    }

    report = {
        "check_id": "CONSUMER",
        "release_id": args.release_id,
        "principal": principal,
        "operator": args.operator,
        "executed_at": now(),
        "manifest_key": manifest_key,
        "manifest_sha256": hashlib.sha256(
            s3.get_object(Bucket=BUCKET, Key=manifest_key)["Body"].read()).hexdigest(),
        "checks": checks,
        "status": "PASS" if all(c["status"] == "PASS" for c in checks.values()) else "FAIL",
    }
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, c in checks.items():
        print(f"{name:<28} {c['status']}")
    print(f"CONSUMER CHECK: {report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
