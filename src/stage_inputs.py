#!/usr/bin/env python3
"""Download S3 inputs and verify them against the trusted manifest."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import boto3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=["s3"])
    parser.add_argument("manifest")
    parser.add_argument("--output-dir", default="/work/staged")
    parser.add_argument("--report", default="/work/stage-report.json")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )

    bucket = os.environ.get("RAW_BUCKET", "research-raw")
    prefix = os.environ.get("INPUT_PREFIX", "lab2/inputs/batch-01").strip("/")

    report = {
        "fixture_version": manifest["fixture_version"],
        "as_of": manifest["as_of"],
        "source": "s3",
        "bucket": bucket,
        "prefix": prefix,
        "objects": [],
        "status": "FAIL",
    }

    all_pass = True

    for obj in manifest["objects"]:
        name = obj["key"]

        # Prevent manifest paths from escaping the staging directory.
        if Path(name).name != name or name in (".", ".."):
            raise ValueError(f"Unsafe object name: {name}")

        s3_key = f"{prefix}/{name}"
        destination = output_dir / name
        temporary = output_dir / (name + ".partial")

        actual_bytes = 0
        digest = hashlib.sha256()
        status = "PASS"
        error = None

        try:
            response = s3.get_object(Bucket=bucket, Key=s3_key)

            with temporary.open("wb") as f:
                for chunk in response["Body"].iter_chunks(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    actual_bytes += len(chunk)
                    digest.update(chunk)

            if actual_bytes != obj["bytes"]:
                raise ValueError("BYTE_MISMATCH")

            if digest.hexdigest().lower() != obj["sha256"].lower():
                raise ValueError("SHA256_MISMATCH")

            temporary.replace(destination)

        except Exception as exc:
            status = "FAIL"
            error = str(exc)
            all_pass = False
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)

        report["objects"].append({
            "key": name,
            "expected_bytes": obj["bytes"],
            "actual_bytes": actual_bytes,
            "expected_sha256": obj["sha256"],
            "actual_sha256": digest.hexdigest(),
            "status": status,
            "reason": error,
        })

        print(f"{name}: {status}", flush=True)

    report["status"] = "PASS" if all_pass else "FAIL"

    Path(args.report).write_text(
        json.dumps(report, indent=2) + "\n"
    )

    print("STAGING:", report["status"])
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
