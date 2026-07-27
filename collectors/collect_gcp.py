"""
Collects GCP Compute Engine instance inventory and (optionally) spend for
one or more projects. Each project can use its own service account key
file, or fall back to your default application credentials.

config shape (see config.example.json):
{
  "enabled": true,
  "cost_lookback_days": 30,
  "projects": [
    {
      "name": "prod-project",
      "project_id": "my-prod-project",
      "credentials_file": "",       # optional path to a service account
                                     # JSON key; blank = use ADC
                                     # (gcloud auth application-default login)
      "billing_bq_table": ""        # optional, see note below
    }
  ]
}

Requires: roles/compute.viewer on each project.

--- One-time setup for cost data (BigQuery billing export) ---
GCP has no simple "get my spend" API like AWS/Azure -- actual cost data
only becomes queryable once you turn on billing export to BigQuery:
  1. Console > Billing > Billing export > BigQuery export > Enable
     "Standard usage cost" export, picking/creating a dataset.
  2. Wait a few hours for the first data to land.
  3. Put the resulting table id (e.g.
     "my-project.billing_export.gcp_billing_export_v1_XXXXXX") into that
     project's "billing_bq_table" field in config.json.
Without it, the dashboard still shows that project's instance inventory,
just no cost panel for it.
"""
import datetime
import os
from google.cloud import compute_v1


def collect_instances(project_id):
    client = compute_v1.InstancesClient()
    agg = client.aggregated_list(project=project_id)

    instances = []
    for zone, response in agg:
        if not response.instances:
            continue
        for inst in response.instances:
            machine_type = inst.machine_type.rsplit("/", 1)[-1] if inst.machine_type else None
            state = inst.status
            if state == "RUNNING":
                state_since = inst.last_start_timestamp or None
            elif state in ("TERMINATED", "STOPPED", "SUSPENDED"):
                state_since = inst.last_stop_timestamp or inst.last_suspended_timestamp or None
            else:
                state_since = None
            labels = dict(inst.labels) if inst.labels else {}
            owner = next((v for k, v in labels.items() if k.lower() == "owner"), None)

            internal_ip = None
            external_ip = None
            if inst.network_interfaces:
                nic = inst.network_interfaces[0]
                internal_ip = nic.network_i_p or None
                if nic.access_configs:
                    external_ip = nic.access_configs[0].nat_i_p or None

            instances.append({
                "id": str(inst.id),
                "name": inst.name,
                "owner": owner,
                "type": machine_type,
                "state": state,
                "state_since": state_since,
                "zone": zone.rsplit("/", 1)[-1],
                "external_ip": external_ip,
                "internal_ip": internal_ip,
                "creation_timestamp": inst.creation_timestamp,
            })
    return instances


def collect_cost_by_service(bq_table, lookback_days=30):
    from google.cloud import bigquery
    client = bigquery.Client()

    end = datetime.date.today()
    start = end - datetime.timedelta(days=lookback_days)

    query = f"""
        SELECT
          service.description AS service,
          SUM(cost) AS total_cost
        FROM `{bq_table}`
        WHERE usage_start_time >= TIMESTAMP(@start)
          AND usage_start_time < TIMESTAMP(@end)
        GROUP BY service
        ORDER BY total_cost DESC
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("start", "STRING", start.isoformat()),
        bigquery.ScalarQueryParameter("end", "STRING", end.isoformat()),
    ])
    rows = list(client.query(query, job_config=job_config).result())

    by_service = [{"service": r.service, "cost": round(float(r.total_cost), 2)} for r in rows]
    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "by_service": by_service,
        "total": round(sum(r["cost"] for r in by_service), 2),
    }


def collect_cost_by_resource(bq_table, lookback_days=30):
    """Best-effort per-instance cost by grouping the billing export on
    resource.name, which for Compute Engine line items is generally the
    instance name itself."""
    from google.cloud import bigquery
    client = bigquery.Client()

    end = datetime.date.today()
    start = end - datetime.timedelta(days=lookback_days)

    query = f"""
        SELECT
          resource.name AS resource_name,
          SUM(cost) AS total_cost
        FROM `{bq_table}`
        WHERE usage_start_time >= TIMESTAMP(@start)
          AND usage_start_time < TIMESTAMP(@end)
          AND resource.name IS NOT NULL
        GROUP BY resource_name
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("start", "STRING", start.isoformat()),
        bigquery.ScalarQueryParameter("end", "STRING", end.isoformat()),
    ])
    rows = list(client.query(query, job_config=job_config).result())
    return {r.resource_name: float(r.total_cost) for r in rows}


def collect_cost_by_day(bq_table, lookback_days=30):
    from google.cloud import bigquery
    client = bigquery.Client()

    end = datetime.date.today()
    start = end - datetime.timedelta(days=lookback_days)

    query = f"""
        SELECT
          DATE(usage_start_time) AS usage_date,
          SUM(cost) AS total_cost
        FROM `{bq_table}`
        WHERE usage_start_time >= TIMESTAMP(@start)
          AND usage_start_time < TIMESTAMP(@end)
        GROUP BY usage_date
        ORDER BY usage_date
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("start", "STRING", start.isoformat()),
        bigquery.ScalarQueryParameter("end", "STRING", end.isoformat()),
    ])
    rows = list(client.query(query, job_config=job_config).result())
    return [{"date": r.usage_date.isoformat(), "cost": round(float(r.total_cost), 2)} for r in rows]


def _scan_one_project(project_cfg, lookback_days):
    name = project_cfg.get("name") or project_cfg.get("project_id") or "default"
    project_id = project_cfg.get("project_id")
    print(f"  [gcp] scanning project '{name}' ({project_id})...")

    creds_file = project_cfg.get("credentials_file") or None
    old_env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_file:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_file

    instances = []
    cost = None
    try:
        try:
            instances = collect_instances(project_id)
            for i in instances:
                i["account"] = name
                i["project_id"] = project_id
            print(f"  [gcp]   found {len(instances)} instances")
        except Exception as exc:
            print(f"  [gcp]   instance listing failed for '{name}': {exc}")

        bq_table = project_cfg.get("billing_bq_table")
        if bq_table:
            try:
                cost = collect_cost_by_service(bq_table, lookback_days)
            except Exception as exc:
                print(f"  [gcp]   cost data unavailable for '{name}' ({exc})")
            if cost is not None:
                try:
                    cost["by_day"] = collect_cost_by_day(bq_table, lookback_days)
                except Exception as exc:
                    print(f"  [gcp]   daily cost breakdown unavailable for '{name}' ({exc})")
            try:
                per_resource = collect_cost_by_resource(bq_table, lookback_days)
                matched = 0
                for i in instances:
                    if i["name"] in per_resource:
                        i["cost"] = round(per_resource[i["name"]], 2)
                        matched += 1
                if matched:
                    print(f"  [gcp]   matched per-instance cost for {matched}/{len(instances)} instances")
            except Exception as exc:
                print(f"  [gcp]   per-resource cost unavailable for '{name}' ({exc})")
        else:
            print(f"  [gcp]   no billing_bq_table configured for '{name}' -- "
                  f"skipping cost panel (see collect_gcp.py header for setup)")
    finally:
        if creds_file:
            if old_env is not None:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = old_env
            else:
                os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

    return {"account": name, "instances": instances, "cost": cost}


def collect(config):
    lookback_days = config.get("cost_lookback_days", 30)
    projects = config.get("projects") or []

    # Backward-compat: allow the old single-project shape too.
    if not projects and config.get("project_id"):
        projects = [{
            "name": config.get("project_id"),
            "project_id": config["project_id"],
            "billing_bq_table": config.get("billing_bq_table"),
        }]

    if not projects:
        raise ValueError("gcp.projects must contain at least one project in config.json")

    results = [_scan_one_project(p, lookback_days) for p in projects]
    return {"provider": "gcp", "accounts": results}
