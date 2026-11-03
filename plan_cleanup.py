"""Prepare, but never apply, a disposable-lab teardown with retained evidence."""

import argparse
import json
import subprocess
from pathlib import Path


def keep(resource):
    kind = resource["type"]
    return (kind.startswith(("aws_s3_", "aws_ecr_", "aws_kms_"))
            or kind in {"aws_cloudwatch_log_group", "aws_sagemaker_model_package_group"}
            # The retained cluster KMS key's policy references this role. A
            # targeted destroy of the role also selects the key and its alias.
            or resource.get("address") == "module.eks.aws_iam_role.this[0]")


def resources(module):
    yield from module.get("resources", [])
    for child in module.get("child_modules", []):
        yield from resources(child)


def selection(state):
    managed = [r for r in resources(state.get("values", {}).get("root_module", {}))
               if r.get("mode") == "managed"]
    retained = sorted(r["address"] for r in managed if keep(r))
    disposable = sorted(r["address"] for r in managed if not keep(r))
    return retained, disposable


def verify_plan(plan, disposable):
    deleted = []
    for change in plan.get("resource_changes", []):
        if change.get("mode") == "data":
            continue
        actions = change["change"]["actions"]
        if actions == ["no-op"]:
            continue
        if actions != ["delete"]:
            raise ValueError("Cleanup plan contains a non-deletion change: " + change["address"])
        if keep(change) or change["address"] not in disposable:
            raise ValueError("Cleanup would delete a retained or unselected resource: " + change["address"])
        deleted.append(change["address"])
    return sorted(deleted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terraform-dir", default="infra")
    parser.add_argument("--var-file", help="Optional private Terraform inputs")
    parser.add_argument("--output", default="evidence/teardown.plan")
    args = parser.parse_args()
    folder, output = Path(args.terraform_dir).resolve(), Path(args.output).resolve()
    if output.exists() or output.with_suffix(".retained.json").exists():
        parser.error("Keep the existing cleanup record; choose a new output filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    tf = ["terraform", "-chdir=" + str(folder)]
    # State and the full plan may contain credentials. Never print or save their
    # JSON; the report below contains only resource addresses and identifiers.
    state = json.loads(subprocess.check_output(tf + ["show", "-json"], text=True))
    retained, disposable = selection(state)
    if not disposable:
        print("Only retained resources remain; no teardown plan was created.")
        return
    command = tf + ["plan", "-destroy", "-input=false", "-out=" + str(output)]
    if args.var_file:
        command.append("-var-file=" + str(Path(args.var_file).resolve()))
    command += ["-target=" + address for address in disposable]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        # Terraform's diagnostic can be inspected locally; it is not a success.
        log = output.with_suffix(".log")
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        raise RuntimeError("Terraform could not prepare cleanup; inspect " + str(log))
    plan = json.loads(subprocess.check_output(tf + ["show", "-json", str(output)], text=True))
    try:
        deleted = verify_plan(plan, disposable)
    except ValueError:
        # Remove only the plan this invocation just created, never a prior plan.
        output.unlink()
        raise
    report = {"retained": retained, "planned_deletions": deleted,
              "note": "Targeting is used only for this disposable-lab teardown. Retained storage, keys, logs and registry records remain in Terraform state and can incur storage charges."}
    output.with_suffix(".retained.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(deleted)} deletions; preserving {len(retained)} evidence/storage resources.")
    print("Review the saved plan and retained-resource report before applying. Nothing was deleted.")


if __name__ == "__main__":
    main()
