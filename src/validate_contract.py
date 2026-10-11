import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

schema_path = Path("data/Lab2-datasets/schemas/observation_contract_schema.json")
contract_path = Path("contracts/contract.json")

schema = json.loads(schema_path.read_text(encoding="utf-8"))
contract = json.loads(contract_path.read_text(encoding="utf-8"))

validator = Draft202012Validator(
    schema,
    format_checker=FormatChecker()
)

errors = list(validator.iter_errors(contract))

if errors:
    print("CONTRACT VALIDATION: FAIL")
    for error in errors:
        print("ERROR:", error.message)
    raise SystemExit(1)

print("CONTRACT VALIDATION: PASS")
print("Schema version:", contract["schema_version"])
print("AS_OF:", contract["as_of"])
print("Required fields:", len(schema["required"]))
