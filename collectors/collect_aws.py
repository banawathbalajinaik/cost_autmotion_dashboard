"""
Collects EC2 instance inventory (all regions) and Cost Explorer spend
(by service, last N days) for one or more AWS accounts, each identified
by a named profile in your ~/.aws/credentials / ~/.aws/config.

config shape (see config.example.json):
{
  "enabled": true,
  "cost_lookback_days": 30,
  "accounts": [
    {"name": "prod", "profile": "prod"},
    {"name": "dev",  "profile": "dev"}
  ]
}

If "accounts" is omitted, falls back to a single scan using your default
credentials (env vars / instance role / [default] profile).

Requires IAM permissions per account: ec2:DescribeRegions,
ec2:DescribeInstances, ce:GetCostAndUsage (Cost Explorer must be enabled
once in the Billing console -- off by default on new accounts).
"""
import datetime
import re
import boto3


def _instance_name(tags):
    for t in tags or []:
        if t.get("Key") == "Name":
            return t.get("Value")
    return None


def _tag_value(tags, key):
    for t in tags or []:
        if (t.get("Key") or "").lower() == key.lower():
            return t.get("Value")
    return None


_STATE_TRANSITION_RE = re.compile(r"\(([^)]+)\)")


def _state_since(inst):
    """Best-effort timestamp for when the instance entered its current
    state. For a running instance this is its LaunchTime (AWS reassigns
    LaunchTime on every start, so it doubles as "running since"). For a
    stopped instance, AWS only exposes this via the free-text
    StateTransitionReason field, e.g. "User initiated (2024-01-15
    08:23:11 GMT)" -- parsed out on a best-effort basis."""
    state = inst["State"]["Name"]
    if state == "running":
        return inst["LaunchTime"].isoformat() if inst.get("LaunchTime") else None

    reason = inst.get("StateTransitionReason") or ""
    match = _STATE_TRANSITION_RE.search(reason)
    if match:
        try:
            dt = datetime.datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S %Z")
            return dt.replace(tzinfo=datetime.timezone.utc).isoformat()
        except ValueError:
            pass
    return None


def collect_instances(session):
    """Returns a list of instance dicts across all regions for one account."""
    ec2_global = session.client("ec2", region_name="us-east-1")
    regions = [r["RegionName"] for r in ec2_global.describe_regions()["Regions"]]

    instances = []
    for region in regions:
        try:
            ec2 = session.client("ec2", region_name=region)
            paginator = ec2.get_paginator("describe_instances")
            for page in paginator.paginate():
                for reservation in page["Reservations"]:
                    for inst in reservation["Instances"]:
                        instances.append({
                            "id": inst["InstanceId"],
                            "name": _instance_name(inst.get("Tags")),
                            "owner": _tag_value(inst.get("Tags"), "Owner"),
                            "type": inst["InstanceType"],
                            "state": inst["State"]["Name"],
                            "region": region,
                            "az": inst.get("Placement", {}).get("AvailabilityZone"),
                            "external_ip": inst.get("PublicIpAddress"),
                            "internal_ip": inst.get("PrivateIpAddress"),
                            "launch_time": inst["LaunchTime"].isoformat()
                                if inst.get("LaunchTime") else None,
                            "state_since": _state_since(inst),
                            "platform": inst.get("PlatformDetails", "Linux/UNIX"),
                        })
        except Exception as exc:
            # Region may be disabled for the account (opt-in regions) -- skip it.
            print(f"    [aws] skipping region {region}: {exc}")
    return instances


def collect_cost_by_day(session, lookback_days=30):
    """Returns total spend per calendar day over the lookback window."""
    ce = session.client("ce", region_name="us-east-1")
    end = datetime.date.today()
    start = end - datetime.timedelta(days=lookback_days)

    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
    )

    by_day = []
    for result in resp.get("ResultsByTime", []):
        date = result["TimePeriod"]["Start"]
        amount = float(result["Total"]["UnblendedCost"]["Amount"])
        by_day.append({"date": date, "cost": round(amount, 2)})
    return by_day


def collect_cost_by_service(session, lookback_days=30):
    """Returns total spend per AWS service over the lookback window for one account."""
    ce = session.client("ce", region_name="us-east-1")
    end = datetime.date.today()
    start = end - datetime.timedelta(days=lookback_days)

    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    totals = {}
    for result in resp.get("ResultsByTime", []):
        for group in result.get("Groups", []):
            service = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            totals[service] = totals.get(service, 0.0) + amount

    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "by_service": [
            {"service": k, "cost": round(v, 2)}
            for k, v in sorted(totals.items(), key=lambda kv: -kv[1])
        ],
        "total": round(sum(totals.values()), 2),
    }


def collect_cost_by_resource(session, lookback_days=14):
    """Best-effort per-instance cost via GetCostAndUsageWithResources.

    NOTE: this AWS API is capped at a 14-day lookback and only returns
    data if "hourly and resource-level data" is enabled in Cost Explorer
    preferences (an extra paid feature). If it's not enabled, this raises
    and the caller should treat per-resource cost as unavailable rather
    than failing the whole account scan.
    """
    ce = session.client("ce", region_name="us-east-1")
    end = datetime.date.today()
    start = end - datetime.timedelta(days=min(lookback_days, 14))

    resp = ce.get_cost_and_usage_with_resources(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter={"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Elastic Compute Cloud - Compute"]}},
        GroupBy=[{"Type": "DIMENSION", "Key": "RESOURCE_ID"}],
    )

    totals = {}
    for result in resp.get("ResultsByTime", []):
        for group in result.get("Groups", []):
            resource_id = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            totals[resource_id] = totals.get(resource_id, 0.0) + amount
    return totals


def _scan_one_account(name, profile, lookback_days):
    print(f"  [aws] scanning account '{name}' (profile={profile or 'default'})...")
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()

    instances = []
    try:
        instances = collect_instances(session)
        for i in instances:
            i["account"] = name
        print(f"  [aws]   found {len(instances)} instances")
    except Exception as exc:
        print(f"  [aws]   instance listing failed for '{name}': {exc}")

    try:
        per_resource = collect_cost_by_resource(session, lookback_days)
        matched = 0
        for i in instances:
            if i["id"] in per_resource:
                i["cost"] = round(per_resource[i["id"]], 2)
                matched += 1
        if matched:
            print(f"  [aws]   matched per-instance cost for {matched}/{len(instances)} instances")
    except Exception as exc:
        print(f"  [aws]   per-resource cost unavailable for '{name}' ({exc}) -- "
              f"needs 'hourly and resource-level data' enabled in Cost Explorer preferences")

    cost = None
    try:
        cost = collect_cost_by_service(session, lookback_days)
    except Exception as exc:
        print(f"  [aws]   cost data unavailable for '{name}' ({exc}) -- "
              f"check Cost Explorer is enabled and ce:GetCostAndUsage is granted")

    if cost is not None:
        try:
            cost["by_day"] = collect_cost_by_day(session, lookback_days)
        except Exception as exc:
            print(f"  [aws]   daily cost breakdown unavailable for '{name}' ({exc})")

    return {"account": name, "instances": instances, "cost": cost}


def collect(config):
    lookback_days = config.get("cost_lookback_days", 30)
    accounts = config.get("accounts") or [{"name": "default", "profile": None}]

    results = []
    for acct in accounts:
        name = acct.get("name") or acct.get("profile") or "default"
        results.append(_scan_one_account(name, acct.get("profile"), lookback_days))

    return {"provider": "aws", "accounts": results}
