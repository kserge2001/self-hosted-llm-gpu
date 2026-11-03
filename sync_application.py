"""Request an Argo CD sync while preserving the application's sync options."""
import argparse
import json
import subprocess


def sync(name, context=None):
    kube = ["kubectl"] + (["--context", context] if context else []) + ["-n", "argocd"]
    application = json.loads(subprocess.check_output(kube + ["get", "application", name, "-o", "json"], text=True))
    if application["spec"].get("project") != "astra":
        raise ValueError("Select an application in the Astra project")
    if application.get("operation"):
        raise ValueError("An operation is already running; check its status before retrying")
    options = application["spec"].get("syncPolicy", {}).get("syncOptions", [])
    patch = {"operation": {"initiatedBy": {"username": "astra-operator"},
                           "sync": {"syncOptions": options}}}
    subprocess.run(kube + ["patch", "application", name, "--type=merge", "-p", json.dumps(patch)], check=True)
    print("Sync requested. Check the application's sync result and workload readiness.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application")
    parser.add_argument("--context")
    args = parser.parse_args()
    sync(args.application, args.context)
