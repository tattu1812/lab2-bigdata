#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_URL = (
    "https://openlineage.io/spec/2-0-2/"
    "OpenLineage.json#/$defs/RunEvent"
)


def now_utc():
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def dataset(namespace, name):
    return {"namespace": namespace, "name": name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    args = parser.parse_args()

    run_id = args.run_id
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        parser.error("run_id chỉ được chứa chữ, số, _ và -")

    namespace = os.environ.get("NS")
    if not namespace:
        parser.error("Hãy chạy source env.sh trước")

    task3_output = ROOT / "outputs/curate" / run_id
    task3_evidence = ROOT / "evidence/task3/runs" / run_id
    task4_evidence = ROOT / "evidence/task4/runs" / run_id

    for path in (task3_output, task3_evidence, task4_evidence):
        if path.exists():
            parser.error(f"Run ID đã có dữ liệu: {path}")

    schema_path = ROOT / "schemas/openlineage-2-0-2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )

    run_uuid = str(uuid.uuid4())
    pod_store = f"k8s://{namespace}/curate"
    local_store = ROOT.as_uri()
    s3_store = "s3://research-raw"

    inputs = [
        dataset(s3_store, "lab2/inputs/batch-01/observations_a.csv"),
        dataset(s3_store, "lab2/inputs/batch-01/observations_b.jsonl"),
        dataset(s3_store, "lab2/inputs/batch-01/sensors.csv"),
        dataset(local_store, "contracts/contract.json"),
        dataset(local_store, "contracts/curation_decisions.json"),
        dataset(pod_store, "/work/envelopes.jsonl"),
        dataset(pod_store, "/work/stage-report.json"),
    ]

    outputs = [
        dataset(
            local_store,
            f"outputs/curate/{run_id}/candidate/curated.parquet",
        ),
        dataset(local_store, f"outputs/curate/{run_id}/quarantine.csv"),
        dataset(local_store, f"outputs/curate/{run_id}/duplicates.csv"),
    ]

    task4_evidence.mkdir(parents=True)
    lineage_path = task4_evidence / "lineage.jsonl"

    def emit(event_type, event_outputs):
        event = {
            "eventTime": now_utc(),
            "eventType": event_type,
            "producer": (ROOT / "src/run_task4_curate.py").as_uri(),
            "schemaURL": SCHEMA_URL,
            "run": {"runId": run_uuid},
            "job": {
                "namespace": pod_store,
                "name": "task3-curation",
            },
            "inputs": inputs,
            "outputs": event_outputs,
        }
        validator.validate(event)
        with lineage_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        print(f"OpenLineage: {event_type}", flush=True)

    emit("START", [])

    try:
        subprocess.run(
            ["bash", str(ROOT / "src/run_task3.sh"), run_id],
            cwd=ROOT,
            check=True,
        )

        for item in outputs:
            path = ROOT / item["name"]
            if not path.is_file():
                raise RuntimeError(f"Thiếu output: {path}")

        emit("COMPLETE", outputs)

    except KeyboardInterrupt:
        emit("ABORT", [])
        raise

    except Exception:
        emit("FAIL", [])
        raise

    print(f"Run UUID: {run_uuid}")
    print(f"Lineage: {lineage_path}")


if __name__ == "__main__":
    main()
