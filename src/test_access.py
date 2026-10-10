#!/usr/bin/env python3
import json
import os
import sys

import boto3
from botocore.exceptions import ClientError

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT"],
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
)

report = {
    "test_id": "I04",
    "principal": "ingestor",
    "get_raw": "FAIL",
    "put_release": "FAIL",
    "put_error": None,
    "put_http_status": None,
    "status": "FAIL",
}

# Test 1: ingestor phải đọc được raw.
try:
    response = s3.get_object(
        Bucket="research-raw",
        Key="lab2/inputs/batch-01/observations_a.csv",
    )
    response["Body"].close()
    report["get_raw"] = "PASS"
except ClientError as exc:
    print("GET RAW failed:", exc.response["Error"]["Code"])

# Test 2: ingestor phải bị từ chối khi ghi release.
try:
    s3.put_object(
        Bucket="research-release",
        Key="lab2/access-tests/i04-ingestor-denied.txt",
        Body=b"I04 access-control test",
    )
    print("WARNING: PUT RELEASE unexpectedly succeeded")

    # Không tự xóa object: ingestor có thể không có quyền xóa.
    # Báo lỗi để người quản trị kiểm tra quyền truy cập.

except ClientError as exc:
    code = exc.response["Error"]["Code"]
    http_status = exc.response["ResponseMetadata"]["HTTPStatusCode"]

    report["put_error"] = code
    report["put_http_status"] = http_status

    if code == "AccessDenied" and http_status == 403:
        report["put_release"] = "PASS"

report["status"] = (
    "PASS"
    if report["get_raw"] == "PASS"
    and report["put_release"] == "PASS"
    else "FAIL"
)

with open("/work/access-test.json", "w") as f:
    json.dump(report, f, indent=2)
    f.write("\n")

print(json.dumps(report, indent=2))
sys.exit(0 if report["status"] == "PASS" else 1)
