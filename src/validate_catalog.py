import csv
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import duckdb
import jsonschema


ROOT = Path(__file__).resolve().parents[1]
errors = []
warnings = []


def fail(message):
    errors.append(message)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_file(path, label, size_bytes, sha256):
    if not path.is_file():
        fail(f"{label}: không tìm thấy file {path}")
        return False

    if path.stat().st_size != size_bytes:
        fail(f"{label}: size_bytes không khớp")

    if sha256_file(path) != sha256:
        fail(f"{label}: SHA-256 không khớp")

    return True


catalog = load_json(ROOT / "catalog.json")
schema = load_json(ROOT / "schemas/catalog.schema.json")

schema_errors = list(
    jsonschema.Draft202012Validator(schema).iter_errors(catalog)
)
for error in schema_errors:
    fail(f"schema: {'.'.join(map(str, error.path))}: {error.message}")

if schema_errors:
    print("CATALOG: FAIL")
    for error in errors:
        print("ERROR:", error)
    sys.exit(1)

datasets = {item["dataset_id"]: item for item in catalog["datasets"]}
if len(datasets) != len(catalog["datasets"]):
    fail("dataset_id bị trùng")

for dataset_id in ("raw", "quarantine", "curated_candidate"):
    if dataset_id not in datasets:
        fail(f"thiếu dataset {dataset_id}")

if errors:
    print("CATALOG: FAIL")
    for error in errors:
        print("ERROR:", error)
    sys.exit(1)

manifest = ROOT / "data/trusted_manifest.json"
contract = ROOT / "contracts/contract.json"
code_files = ["src/curate.sql", "src/run_curate.py", "src/run_task3.sh", "src/run_task4_curate.py", "src/test_curate.py", "src/validate_contract.py"]

code_lines = "".join(
    f"{sha256_file(ROOT / name)}  {name}\n"
    for name in sorted(code_files)
)
code_sha256 = hashlib.sha256(code_lines.encode("utf-8")).hexdigest()

for dataset in catalog["datasets"]:
    dataset_id = dataset["dataset_id"]

    names = [column["name"] for column in dataset["columns"]]
    if len(names) != len(set(names)):
        fail(f"{dataset_id}: tên cột bị trùng")

    for field, path in (
        ("input_manifest_sha256", manifest),
        ("contract_sha256", contract),
    ):
        if not path.is_file() or dataset[field] != sha256_file(path):
            fail(f"{dataset_id}: {field} không khớp file thực tế")

    if dataset["code_sha256"] != code_sha256:
        fail(f"{dataset_id}: code_sha256 không khớp bộ mã hiện tại")

    quality_path = ROOT / dataset["quality_report"]
    if not quality_path.is_file():
        fail(f"{dataset_id}: thiếu quality report {quality_path}")

    if dataset_id == "raw":
        continue

    locations = dataset["location"]
    if len(locations) != 1:
        fail(f"{dataset_id}: cần đúng một location cho artifact này")
        continue

    uri = urlparse(locations[0]["uri"])
    if uri.scheme != "file":
        fail(f"{dataset_id}: location phải là file URI")
        continue

    path = Path(unquote(uri.path))
    if not check_file(
        path, dataset_id, dataset["size_bytes"], dataset["sha256"]
    ):
        continue

    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            actual_columns = reader.fieldnames or []
            actual_rows = sum(1 for _ in reader)

        if actual_columns != names:
            fail(f"{dataset_id}: columns không khớp header CSV")
        if actual_rows != dataset["row_count"]:
            fail(f"{dataset_id}: row_count không khớp CSV")

    elif path.suffix == ".parquet":
        connection = duckdb.connect()
        try:
            actual_rows = connection.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(path)]
            ).fetchone()[0]

            description = connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
            actual_columns = [row[0] for row in description]
            actual_types = {row[0]: row[1].upper() for row in description}

            if actual_rows != dataset["row_count"]:
                fail(f"{dataset_id}: row_count không khớp Parquet")
            if actual_columns != names:
                fail(f"{dataset_id}: columns không khớp Parquet")

            for column in dataset["columns"]:
                name = column["name"]
                expected_type = column["type"].upper()
                if name in actual_types and actual_types[name] != expected_type:
                    fail(
                        f"{dataset_id}: kiểu cột {name} là "
                        f"{actual_types[name]}, catalog ghi {expected_type}"
                    )

                if name in actual_types and not column["nullable"]:
                    quoted_name = name.replace('"', '""')
                    null_count = connection.execute(
                        f'SELECT count(*) FROM read_parquet(?) '
                        f'WHERE "{quoted_name}" IS NULL',
                        [str(path)],
                    ).fetchone()[0]
                    if null_count:
                        fail(f"{dataset_id}: cột {name} có {null_count} NULL")
        finally:
            connection.close()

    else:
        fail(f"{dataset_id}: định dạng file chưa được hỗ trợ")


raw = datasets["raw"]
source_objects = raw.get("source_objects", [])
source_names = [item["name"] for item in source_objects]

if set(source_names) != set(raw.get("source_aliases", {})):
    fail("raw: source_aliases không khớp source_objects")

stage_path = (
    ROOT
    / "evidence/task1/runs"
    / raw["provenance"]["source_run_id"]
    / "stage-report.json"
)
if not stage_path.is_file():
    stage_path = ROOT / "evidence/task1/stage-report.json"
    warnings.append("Dùng stage-report.json chung; chưa xác nhận report theo run_id")

if stage_path.is_file():
    stage = load_json(stage_path)
    staged = {item["key"]: item for item in stage["objects"]}
else:
    staged = {}
    fail("raw: không tìm thấy stage report")

raw_uris = {item["uri"] for item in raw["location"]}
raw_columns = set()
total_rows = 0
total_bytes = 0

for source in source_objects:
    name = source["name"]
    path = ROOT / "data/Lab2-datasets/input" / name

    if not check_file(path, f"raw/{name}", source["size_bytes"], source["sha256"]):
        continue

    total_bytes += source["size_bytes"]

    if name.endswith(".csv"):
        with path.open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            raw_columns.update(reader.fieldnames or [])
            count = sum(1 for _ in reader)
    elif name.endswith(".jsonl"):
        with path.open(encoding="utf-8") as file:
            first_line = file.readline()
            raw_columns.update(json.loads(first_line).keys())
            count = 1 + sum(1 for _ in file)
    else:
        fail(f"raw: định dạng nguồn không hỗ trợ: {name}")
        continue

    total_rows += count
    if count != source["row_count"]:
        fail(f"raw/{name}: row_count không khớp")

    item = staged.get(name)
    if (
        item is None
        or item["status"] != "PASS"
        or item["actual_bytes"] != source["size_bytes"]
        or item["actual_sha256"] != source["sha256"]
    ):
        fail(f"raw/{name}: không khớp stage report")

    expected_uri = f"s3://{stage['bucket']}/{stage['prefix']}/{name}"
    if expected_uri not in raw_uris:
        fail(f"raw/{name}: thiếu S3 URI trong location")

if total_rows != raw["row_count"]:
    fail("raw: tổng row_count không khớp")

if total_bytes != raw["size_bytes"]:
    fail("raw: tổng size_bytes không khớp")

if raw_columns != {column["name"] for column in raw["columns"]}:
    fail("raw: columns không khớp hai nguồn đầu vào")

for artifact in catalog["artifacts"]:
    path = ROOT / artifact["location"]
    label = artifact["artifact_id"]
    if not check_file(
        path, label, artifact["size_bytes"], artifact["sha256"]
    ):
        continue

    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as file:
            actual_rows = sum(1 for _ in csv.DictReader(file))
        if actual_rows != artifact["row_count"]:
            fail(f"{label}: row_count không khớp")

warnings.append("S3 URI được đối chiếu với stage report, chưa đọc trực tiếp từ S3")

print("CATALOG:", "FAIL" if errors else "PASS")
for error in errors:
    print("ERROR:", error)
for warning in warnings:
    print("WARNING:", warning)

sys.exit(1 if errors else 0)
