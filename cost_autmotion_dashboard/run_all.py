"""
Runs whichever cloud collectors are enabled in config.json, saves their
raw output under data/, then generates dashboard.html from the combined
result.

Usage:
    python run_all.py
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
CONFIG_PATH = os.path.join(HERE, "config.json")
CONFIG_EXAMPLE_PATH = os.path.join(HERE, "config.example.json")

sys.path.insert(0, HERE)


def load_config():
    if not os.path.exists(CONFIG_PATH):
        shutil.copy(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
        print(f"Created {CONFIG_PATH} from the example template -- "
              f"edit it (subscription_id / project_id) and re-run.")
    with open(CONFIG_PATH) as f:
        return json.load(f)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    config = load_config()

    results = {}

    if config.get("aws", {}).get("enabled"):
        from collectors import collect_aws
        try:
            results["aws"] = collect_aws.collect(config["aws"])
        except Exception as exc:
            print(f"[aws] collection failed entirely: {exc}")
            results["aws"] = {"provider": "aws", "accounts": [], "error": str(exc)}

    if config.get("azure", {}).get("enabled"):
        from collectors import collect_azure
        try:
            results["azure"] = collect_azure.collect(config["azure"])
        except Exception as exc:
            print(f"[azure] collection failed entirely: {exc}")
            results["azure"] = {"provider": "azure", "accounts": [], "error": str(exc)}

    if config.get("gcp", {}).get("enabled"):
        from collectors import collect_gcp
        try:
            results["gcp"] = collect_gcp.collect(config["gcp"])
        except Exception as exc:
            print(f"[gcp] collection failed entirely: {exc}")
            results["gcp"] = {"provider": "gcp", "accounts": [], "error": str(exc)}

    for provider, data in results.items():
        out_path = os.path.join(DATA_DIR, f"{provider}.json")
        with open(out_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"wrote {out_path}")

    from generate_dashboard import generate
    dashboard_path = generate(results, os.path.join(HERE, "dashboard.html"))
    print(f"\nDashboard written to {dashboard_path} -- open it in a browser.")


if __name__ == "__main__":
    main()
