import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path.cwd()
CATALOG_PATH = ROOT / "catalog.json"
SCHEMA_PATH = ROOT / "schemas/catalog.schema.json"

catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

errors = []
warnings = []

for field in schema["required"]:
    if field not in catalog:
        errors.append(f"catalog thiếu field: {field}")

dataset_schema = schema["$defs"]["dataset"]
required_dataset_fields = dataset_schema["required"]

datasets = catalog.get("datasets", [])

if len(datasets) < 3:
    errors.append("catalog phải có ít nhất 3 dataset")

def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def resolve_location(location):
    if location.startswith("s3://"):
        return None
    path = Path(location)
    return path if path.is_absolute() else ROOT / path

def check_dataset(dataset):
    dataset_id = dataset.get("dataset_id", "<unknown>")

    for field in required_dataset_fields:
        if field not in dataset:
            errors.append(f"{dataset_id}: thiếu field {field}")

    sha = dataset.get("sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        errors.append(f"{dataset_id}: sha256 không đúng định dạng")

    row_count = dataset.get("row_count")
    if not isinstance(row_count, int) or row_count < 0:
        errors.append(f"{dataset_id}: row_count không hợp lệ")

    size_bytes = dataset.get("size_bytes")
    if not isinstance(size_bytes, int) or size_bytes < 0:
        errors.append(f"{dataset_id}: size_bytes không hợp lệ")

    location = dataset.get("location", "")
    path = resolve_location(location)

    if path is None:
        warnings.append(f"{dataset_id}: location S3 chưa kiểm tra trực tiếp")
        return

    if not path.exists():
        errors.append(f"{dataset_id}: file không tồn tại: {path}")
        return

    actual_size = path.stat().st_size
    if actual_size != size_bytes:
        errors.append(
            f"{dataset_id}: size_bytes sai; catalog={size_bytes}, "
            f"actual={actual_size}"
        )

    actual_hash = sha256_file(path)
    if actual_hash != sha:
        errors.append(
            f"{dataset_id}: sha256 sai; catalog={sha}, actual={actual_hash}"
        )

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            actual_columns = reader.fieldnames or []
            actual_rows = sum(1 for _ in reader)

        if actual_rows != row_count:
            errors.append(
                f"{dataset_id}: row_count sai; catalog={row_count}, "
                f"actual={actual_rows}"
            )

        if actual_columns != dataset.get("columns", []):
            errors.append(
                f"{dataset_id}: columns không khớp với header CSV"
            )

    elif path.suffix.lower() == ".parquet":
        try:
            import duckdb

            connection = duckdb.connect()
            actual_rows = connection.execute(
                "SELECT count(*) FROM read_parquet(?)",
                [str(path)]
            ).fetchone()[0]

            actual_columns = [
                row[0]
                for row in connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)",
                    [str(path)]
                ).fetchall()
            ]

            connection.close()

            if actual_rows != row_count:
                errors.append(
                    f"{dataset_id}: row_count sai; catalog={row_count}, "
                    f"actual={actual_rows}"
                )

            if actual_columns != dataset.get("columns", []):
                errors.append(
                    f"{dataset_id}: columns không khớp với Parquet"
                )

        except ImportError:
            errors.append(
                "Không tìm thấy duckdb; cần chạy validator trong môi trường "
                "có duckdb để kiểm tra Parquet"
            )

for dataset in datasets:
    check_dataset(dataset)

if errors:
    print("CATALOG: FAIL")
    for error in errors:
        print("ERROR:", error)
    for warning in warnings:
        print("WARNING:", warning)
    sys.exit(1)

print("CATALOG: PASS")
for warning in warnings:
    print("WARNING:", warning)
