"""Collect official CVE file evidence; never approve or suppress a finding."""

import argparse
import concurrent.futures
import hashlib
import json
import urllib.request
from pathlib import Path


def collect(identifier, directory):
    year, number = identifier.split("-")[1:]
    url = f"https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/{year}/{number[:-3]}xxx/{identifier}.json"
    path = directory / (identifier + ".json")
    try:
        if path.exists():
            raw = path.read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=30) as response:
                raw = response.read(2 * 1024 * 1024)
            path.write_bytes(raw)
        record = json.loads(raw)
        affected = record["containers"]["cna"]["affected"]
        files = sorted({file for product in affected for file in product.get("programFiles", [])})
        products = sorted({product.get("product", "") for product in affected})
        # UAPI files can be installed by linux-libc-dev: these need manual review.
        return {"cve": identifier, "source": url, "sha256": hashlib.sha256(raw).hexdigest(),
                "products": products, "program_files": files,
                "needs_file_review": not files or any("uapi/" in file for file in files),
                "approved": False}
    except Exception as error:
        return {"cve": identifier, "source": url, "needs_file_review": True,
                "error": type(error).__name__ + ": " + str(error), "approved": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scan")
    parser.add_argument("output_directory")
    args = parser.parse_args()
    directory = Path(args.output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    scan = json.loads(Path(args.scan).read_bytes())
    identifiers = sorted({v["VulnerabilityID"] for result in scan["Results"]
                          for v in result.get("Vulnerabilities", [])
                          if v["PkgName"] == "linux-libc-dev" and v["Severity"] in ("HIGH", "CRITICAL")})
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        records = list(executor.map(lambda identifier: collect(identifier, directory), identifiers))
    output = {"approved": False, "scope": "container header findings only; no host-kernel conclusion",
              "scan_sha256": hashlib.sha256(Path(args.scan).read_bytes()).hexdigest(), "findings": records}
    (directory / "review.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(records), "needs_file_review": sum(r["needs_file_review"] for r in records),
                      "errors": sum("error" in r for r in records), "approved": False}))


if __name__ == "__main__":
    main()
