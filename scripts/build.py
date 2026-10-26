#!/usr/bin/env python3
"""Build Lambda packages into build/<function>/ (Terraform zips them).

Cross-platform (Windows, macOS, Linux): dependencies are downloaded as Linux wheels
for the Lambda architecture, so no Docker or WSL is needed.

Usage:  python scripts/build.py            (arm64, default)
        python scripts/build.py --arch x86_64
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS = ["gateway", "mcp_server"]
PLATFORMS = {
    "arm64": ["manylinux_2_28_aarch64", "manylinux2014_aarch64"],
    "x86_64": ["manylinux_2_28_x86_64", "manylinux2014_x86_64"],
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arch", choices=PLATFORMS, default="arm64", help="must match var.lambda_architecture")
    args = p.parse_args()

    build, dist = ROOT / "build", ROOT / "dist"
    for d in (build, dist):
        shutil.rmtree(d, ignore_errors=True)
    dist.mkdir()

    for fn in FUNCTIONS:
        src, out = ROOT / "app" / fn, build / fn
        out.mkdir(parents=True)
        print(f"==> {fn} ({args.arch})", flush=True)
        cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "--target", str(out),
               "--implementation", "cp", "--python-version", "3.12", "--only-binary=:all:",
               "-r", str(src / "requirements.txt")]
        for plat in PLATFORMS[args.arch]:
            cmd += ["--platform", plat]
        subprocess.run(cmd, check=True)
        for py in src.glob("*.py"):
            shutil.copy2(py, out / py.name)
        shutil.copytree(ROOT / "app" / "common", out / "common",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for cache in out.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)

    print("Build complete. Next: terraform -chdir=terraform apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
