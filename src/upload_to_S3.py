import os
import boto3
from pathlib import Path

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT"],
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
)

bucket = "research-raw"
prefix = "lab2/inputs/batch-01"

files = [
    "observations_a.csv",
    "observations_b.jsonl",
    "qa_reference.csv",
    "sensors.csv",
]

for name in files:
    path = Path("/tmp/lab2-inputs") / name
    key = f"{prefix}/{name}"

    s3.upload_file(str(path), bucket, key)
    print(f"UPLOADED: s3://{bucket}/{key}", flush=True)

print("UPLOAD COMPLETE")