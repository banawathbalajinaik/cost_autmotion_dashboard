"""
Collects Azure VM inventory and Cost Management spend for one or more
"directories" (Azure AD tenants), each scanning one or more subscriptions
within that tenant.

config shape (see config.example.json):
{
  "enabled": true,
  "cost_lookback_days": 30,
  "directories": [
    {
      "name": "main-tenant",
      "tenant_id": "",          # optional if using az login for a single tenant
      "client_id": "",          # set these three together for a service
      "client_secret": "",      # principal; leave blank to use az login /
                                 # DefaultAzureCredential instead
      "subscription_ids": []    # leave empty to auto-discover every
                                 # subscription reachable in this tenant
    }
  ]
}

Requires: Reader role on each subscription, plus Cost Management Reader
for the cost query.
"""
import datetime
import os
from azure.identity import DefaultAzureCredential, ClientSecretCredential
from azure.mgmt.subscription import SubscriptionClient
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.costmanagement.models import (
    QueryDefinition, QueryTimePeriod, QueryDataset,
    QueryAggregation, QueryGrouping,
)


def _credential_for(directory):
    """Resolves credentials for one directory (tenant).

    Three ways to supply credentials, checked in order:
    1. tenant_id_env / client_id_env / client_secret_env -- names of
       environment variables holding the actual values (e.g. injected by
       Cloud Build's secretEnv). This is the recommended way to support
       more than one directory, since each needs its own service
       principal, and it keeps config.json free of literal secrets.
    2. tenant_id / client_id / client_secret -- literal values directly
       in config.json. Fine for local/manual runs, not recommended for
       anything committed to git.
    3. None of the above configured at all -- falls back to
       DefaultAzureCredential(), which reads the single global
       AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET env vars.
       Only safe for a single directory.

    IMPORTANT: if _env fields ARE specified but the environment variables
    they name aren't actually set (a misconfigured secret, typo, etc.),
    this raises rather than silently falling back to
    DefaultAzureCredential() -- that fallback would otherwise pick up
    *whatever* AZURE_TENANT_ID/etc happen to be in the process
    environment, which in a multi-directory build is very likely a
    DIFFERENT directory's credentials. Silently authenticating as the
    wrong tenant is worse than a loud, obvious error.
    """
    uses_env_indirection = any(
        directory.get(k) for k in ("tenant_id_env", "client_id_env", "client_secret_env")
    )

    tenant_id = (
        os.environ.get(directory.get("tenant_id_env", ""))
        or directory.get("tenant_id")
        or None
    )
    client_id = (
        os.environ.get(directory.get("client_id_env", ""))
        or directory.get("client_id")
        or None
    )
    client_secret = (
        os.environ.get(directory.get("client_secret_env", ""))
        or directory.get("client_secret")
        or None
    )

    if tenant_id and client_id and client_secret:
        return ClientSecretCredential(tenant_id, client_id, client_secret)

    if uses_env_indirection:
        missing = [
            name for name, val in [
                (directory.get("tenant_id_env"), tenant_id),
                (directory.get("client_id_env"), client_id),
                (directory.get("client_secret_env"), client_secret),
            ] if not val
        ]
        raise RuntimeError(
            f"directory '{directory.get('name')}' specifies env-var credential fields, "
            f"but these environment variables are not set (or empty): {missing}. "
            f"Refusing to fall back to DefaultAzureCredential() here, since that could "
            f"silently authenticate as a DIFFERENT directory's credentials instead. "
            f"Check cloudbuild.yaml's secretEnv/availableSecrets and the Secret Manager "
            f"secrets themselves."
        )

    return DefaultAzureCredential()


def _discover_subscriptions(credential):
    sub_client = SubscriptionClient(credential)
    return [s.subscription_id for s in sub_client.subscriptions.list()]


def _power_state(instance_view):
    """Returns (state, state_since_iso) from the VM's instance view
    statuses. Azure tracks a timestamp per status, so the PowerState
    status's time doubles as "since when has it been in this state"
    for both running and stopped/deallocated VMs."""
    for status in (instance_view.statuses if instance_view else []):
        if status.code and status.code.startswith("PowerState/"):
            state = status.code.split("/", 1)[1]
            since = status.time.isoformat() if status.time else None
            return state, since
    return "unknown", None


def _vm_ips(network_client, vm):
    """Best-effort internal/external IP lookup for a VM's primary NIC.
    Costs 1-2 extra API calls per VM, so failures here are swallowed --
    a missing IP shouldn't break the whole instance listing."""
    internal_ip, external_ip = None, None
    try:
        if not vm.network_profile or not vm.network_profile.network_interfaces:
            return None, None
        nic_id = vm.network_profile.network_interfaces[0].id
        nic_rg = nic_id.split("/")[4]
        nic_name = nic_id.split("/")[-1]
        nic = network_client.network_interfaces.get(nic_rg, nic_name)
        if nic.ip_configurations:
            ip_config = nic.ip_configurations[0]
            internal_ip = ip_config.private_ip_address
            if ip_config.public_ip_address:
                pip_id = ip_config.public_ip_address.id
                pip_rg = pip_id.split("/")[4]
                pip_name = pip_id.split("/")[-1]
                pip = network_client.public_ip_addresses.get(pip_rg, pip_name)
                external_ip = pip.ip_address
    except Exception:
        pass
    return internal_ip, external_ip


def collect_instances(credential, subscription_ids):
    instances = []
    for sub_id in subscription_ids:
        compute = ComputeManagementClient(credential, sub_id)
        network_client = NetworkManagementClient(credential, sub_id)
        for vm in compute.virtual_machines.list_all():
            rg = vm.id.split("/")[4]  # .../resourceGroups/<rg>/...
            size = vm.hardware_profile.vm_size if vm.hardware_profile else None
            tags = vm.tags or {}
            owner = next((v for k, v in tags.items() if k.lower() == "owner"), None)
            internal_ip, external_ip = _vm_ips(network_client, vm)
            entry = {
                "id": vm.id,
                "vm_id": vm.vm_id,
                "name": vm.name,
                "owner": owner,
                "type": size,
                "state": "unknown",
                "state_since": None,
                "region": vm.location,
                "resource_group": rg,
                "subscription_id": sub_id,
                "external_ip": external_ip,
                "internal_ip": internal_ip,
                "os": vm.storage_profile.os_disk.os_type
                    if vm.storage_profile and vm.storage_profile.os_disk else None,
            }
            try:
                iv = compute.virtual_machines.instance_view(rg, vm.name)
                entry["state"], entry["state_since"] = _power_state(iv)
            except Exception:
                pass
            instances.append(entry)
    return instances


def collect_cost_by_service(credential, subscription_ids, lookback_days=30):
    client = CostManagementClient(credential)
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=lookback_days)

    totals = {}
    for sub_id in subscription_ids:
        scope = f"/subscriptions/{sub_id}"
        query = QueryDefinition(
            type="ActualCost",
            timeframe="Custom",
            time_period=QueryTimePeriod(from_property=start, to=end),
            dataset=QueryDataset(
                granularity="None",
                aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
                grouping=[QueryGrouping(type="Dimension", name="ServiceName")],
            ),
        )
        try:
            result = client.query.usage(scope, query)
            for row in result.rows:
                # Column order matches dataset.aggregation/grouping above:
                # [Cost, ServiceName, Currency]
                cost_amount, service_name = row[0], row[1]
                totals[service_name] = totals.get(service_name, 0.0) + float(cost_amount)
        except Exception as exc:
            print(f"    [azure] cost query failed for subscription {sub_id}: {exc}")

    return {
        "period_start": start.date().isoformat(),
        "period_end": end.date().isoformat(),
        "by_service": [
            {"service": k, "cost": round(v, 2)}
            for k, v in sorted(totals.items(), key=lambda kv: -kv[1])
        ],
        "total": round(sum(totals.values()), 2),
    }


def collect_cost_by_resource(credential, subscription_ids, lookback_days=30):
    """Best-effort per-VM cost via Cost Management grouped by ResourceId."""
    client = CostManagementClient(credential)
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=lookback_days)

    totals = {}
    for sub_id in subscription_ids:
        scope = f"/subscriptions/{sub_id}"
        query = QueryDefinition(
            type="ActualCost",
            timeframe="Custom",
            time_period=QueryTimePeriod(from_property=start, to=end),
            dataset=QueryDataset(
                granularity="None",
                aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
                grouping=[QueryGrouping(type="Dimension", name="ResourceId")],
            ),
        )
        try:
            result = client.query.usage(scope, query)
            for row in result.rows:
                cost_amount, resource_id = row[0], row[1]
                totals[resource_id] = totals.get(resource_id, 0.0) + float(cost_amount)
        except Exception as exc:
            print(f"    [azure] per-resource cost query failed for subscription {sub_id}: {exc}")
    return totals


def collect_cost_by_day(credential, subscription_ids, lookback_days=30):
    client = CostManagementClient(credential)
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=lookback_days)

    totals = {}
    for sub_id in subscription_ids:
        scope = f"/subscriptions/{sub_id}"
        query = QueryDefinition(
            type="ActualCost",
            timeframe="Custom",
            time_period=QueryTimePeriod(from_property=start, to=end),
            dataset=QueryDataset(
                granularity="Daily",
                aggregation={"totalCost": QueryAggregation(name="Cost", function="Sum")},
            ),
        )
        try:
            result = client.query.usage(scope, query)
            # Column order for a Daily-granularity query with no grouping is
            # [Cost, UsageDate, Currency].
            for row in result.rows:
                cost_amount, usage_date = row[0], row[1]
                date_str = str(usage_date)
                date_str = f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}" if len(date_str) == 8 else date_str
                totals[date_str] = totals.get(date_str, 0.0) + float(cost_amount)
        except Exception as exc:
            print(f"    [azure] daily cost query failed for subscription {sub_id}: {exc}")

    return [{"date": d, "cost": round(c, 2)} for d, c in sorted(totals.items())]


def _scan_one_directory(directory, lookback_days):
    name = directory.get("name") or directory.get("tenant_id") or "default"
    print(f"  [azure] scanning directory '{name}'...")

    credential = _credential_for(directory)
    subscription_ids = directory.get("subscription_ids") or []
    if not subscription_ids:
        try:
            subscription_ids = _discover_subscriptions(credential)
            print(f"  [azure]   auto-discovered {len(subscription_ids)} subscription(s)")
        except Exception as exc:
            print(f"  [azure]   subscription discovery failed for '{name}': {exc}")
            subscription_ids = []

    instances = []
    try:
        instances = collect_instances(credential, subscription_ids)
        for i in instances:
            i["account"] = name
        print(f"  [azure]   found {len(instances)} VMs")
    except Exception as exc:
        print(f"  [azure]   instance listing failed for '{name}': {exc}")

    try:
        per_resource = collect_cost_by_resource(credential, subscription_ids, lookback_days)
        # Cost Management returns resource ids in whatever casing Azure stored
        # them with, which can differ from the ARM id casing on the VM object.
        per_resource_lower = {k.lower(): v for k, v in per_resource.items()}
        matched = 0
        for i in instances:
            v = per_resource_lower.get(i["id"].lower())
            if v is not None:
                i["cost"] = round(v, 2)
                matched += 1
        if matched:
            print(f"  [azure]   matched per-instance cost for {matched}/{len(instances)} VMs")
    except Exception as exc:
        print(f"  [azure]   per-resource cost unavailable for '{name}' ({exc})")

    cost = None
    try:
        cost = collect_cost_by_service(credential, subscription_ids, lookback_days)
    except Exception as exc:
        print(f"  [azure]   cost data unavailable for '{name}' ({exc})")

    if cost is not None:
        try:
            cost["by_day"] = collect_cost_by_day(credential, subscription_ids, lookback_days)
        except Exception as exc:
            print(f"  [azure]   daily cost breakdown unavailable for '{name}' ({exc})")

    return {"account": name, "instances": instances, "cost": cost}


def collect(config):
    lookback_days = config.get("cost_lookback_days", 30)
    directories = config.get("directories") or [{"name": "default"}]

    results = []
    for d in directories:
        name = d.get("name") or d.get("tenant_id") or "default"
        try:
            results.append(_scan_one_directory(d, lookback_days))
        except Exception as exc:
            print(f"[azure] directory '{name}' failed entirely: {exc}")
            results.append({"account": name, "instances": [], "cost": None, "error": str(exc)})

    return {"provider": "azure", "accounts": results}
