# Datadog Monitoring

This directory deploys the Datadog stack on the `lahoucine-cluster` EKS cluster:

- **Datadog Operator** — manages the agent lifecycle via the `DatadogAgent` CRD
- **Datadog Agent** (DaemonSet) — collects metrics, traces, and logs from every node
- **Cluster Agent** — kube-state, orchestrator explorer, admission controller (APM single-step injection)
- **Observability Pipelines Worker (OPW)** — receives logs from the agent and forwards them to Cloudprem per the pipeline defined in the Datadog UI
- **Cloudprem** — self-hosted log store built on [Quickwit](https://quickwit.io/); indexers receive logs from OPW and write splits to S3, searchers serve queries back to the Datadog UI

## Architecture

```
[ Datadog Operator ]
        |
        v reconciles
[ DatadogAgent CR ] --> [ Cluster Agent ]      [ Datadog Agent (DaemonSet) ]
                                                       |
                                  metrics + APM  ----->|------> Datadog SaaS (datadoghq.com)
                                                       |
                                       logs ---------->[ OPW (StatefulSet) ] ----> [ Cloudprem ]
                                                                                       |
                                                                            splits ---->[ S3 ]
                                                                          metastore --->[ RDS Postgres ]
                                                                          searches  ---> Datadog UI (via ingress)
```

Logs path is **Option 1** in [datadog.yaml](datadog.yaml): Agent → OPW → Cloudprem. The Cloudprem destination is defined inside the OPW pipeline in the Datadog UI. Cloudprem itself runs in-cluster (its own namespace) and is deployed via the helm chart in the companion [CloudPrem repo](https://github.com/DataDog/cloudprem) (referenced as `../CloudPrem` locally).

## Files

| File | Purpose |
|---|---|
| [datadog.yaml](datadog.yaml) | `DatadogAgent` CR (operator-managed) — cluster name, log collection, APM single-step, features |
| [opw-values.yaml](opw-values.yaml) | Helm values for the Observability Pipelines Worker chart |

## Prerequisites

- EKS cluster `lahoucine-cluster` deployed and `kubectl` configured (see top-level `README.md`)
- AWS Load Balancer Controller installed
- A Datadog API key with the `Agent` permission scope
- An Observability Pipelines pipeline created in the Datadog UI with:
  - A **Datadog Agent** source (listening on `0.0.0.0:8282`)
  - A destination configured for your Cloudprem indexer (e.g. `http://cp-cloudprem-indexer.<cloudprem-ns>.svc.cluster.local:7280`)
  - The pipeline ID copied for `--set datadog.pipelineId=...`
- For Cloudprem (step 4): the [`CloudPrem` repo](../../CloudPrem) cloned locally, plus the AWS resources it requires (RDS PostgreSQL metastore, S3 bucket, IRSA role). Deploy [`CloudPrem/cloudformation/template.yaml`](../../CloudPrem/cloudformation/template.yaml) and note the outputs (`DatabaseEndpoint`, `S3BucketName`, `IRSARoleName`).

## 1. Create the namespace and API key secret

```bash
kubectl create namespace datadog

kubectl create secret generic datadog-secret \
  --from-literal api-key=$DD_API_KEY \
  -n datadog
```

`api-key` is the key name referenced in [datadog.yaml](datadog.yaml) under `global.credentials.apiSecret.keyName` — keep them in sync.

## 2. Install the Datadog Operator

```bash
helm repo add datadog https://helm.datadoghq.com
helm repo update

helm install datadog-operator datadog/datadog-operator -n datadog
```

Verify:

```bash
kubectl get pods -n datadog -l app.kubernetes.io/name=datadog-operator
```

## 3. Install the Observability Pipelines Worker (OPW)

OPW must run in the `datadog` namespace so the agent's log destination URL in [datadog.yaml:23](datadog.yaml) resolves:

```yaml
DD_OBSERVABILITY_PIPELINES_WORKER_LOGS_URL:
  http://opw-observability-pipelines-worker.datadog.svc.cluster.local:8282
```

Install:

```bash
helm upgrade --install opw -n datadog \
  -f datadog/opw-values.yaml \
  --set datadog.apiKey=$DD_API_KEY \
  --set datadog.pipelineId=$DD_PIPELINE_ID \
  datadog/observability-pipelines-worker
```

**Required env var.** The OPW pipeline (defined in the Datadog UI) references a placeholder for the Datadog Agent source's listen address. [opw-values.yaml](opw-values.yaml) already injects this:

```yaml
env:
  - name: DD_OP_SOURCE_DATADOG_AGENT_ADDRESS
    value: "0.0.0.0:8282"
  - name: SOURCE_DATADOG_AGENT_ADDRESS
    value: "0.0.0.0:8282"
```

Both names are set because OPW's remote-config validator expects the `DD_OP_*` form, while the pipeline template substitution uses the unprefixed form. Without these, OPW logs:

```
ERROR Configuration is invalid.
errors=["Missing configuration option for identifier: SOURCE_DATADOG_AGENT_ADDRESS"]
```

If your pipeline references additional placeholders (e.g. a destination URL), add matching `DD_OP_<NAME>` env vars to [opw-values.yaml](opw-values.yaml).

Verify OPW is listening:

```bash
kubectl get pods,svc -n datadog -l app.kubernetes.io/name=observability-pipelines-worker
kubectl logs -n datadog opw-observability-pipelines-worker-0 --tail=20
```

You should see `Healthcheck passed.` and no `Missing configuration option` errors.

## 4. Deploy Cloudprem (logs destination)

Cloudprem is the in-cluster log store that OPW forwards to. The full chart, values templates, and a standalone CFN template for RDS + S3 + IRSA live in the companion [`CloudPrem` repo](../../CloudPrem) — these steps summarize the deploy from there as it relates to this stack.

### 4.1 Provision Cloudprem AWS resources

Cloudprem needs:

- An **RDS PostgreSQL** instance for the metastore (index metadata)
- An **S3 bucket** for split storage (the indexed log data)
- An **IAM role for IRSA** granting the Cloudprem service account read/write on that bucket

Deploy [`cloudformation/template.yaml`](../../CloudPrem/cloudformation/template.yaml) from the CloudPrem repo as a separate stack (e.g. `lahoucine-cloudprem`). From its **Outputs** tab, note:

| Output | Used for |
|---|---|
| `DatabaseEndpoint` | `QW_METASTORE_URI` in the metastore secret |
| `S3BucketName` | `default_index_root_uri` in `cp-values.yaml` |
| `IRSARoleName` | `serviceAccount.eksRoleName` in `cp-values.yaml` |

> If you already have an EKS cluster (you do — `lahoucine-cluster`), point the CloudPrem CFN parameters at it instead of letting it create a new one. Otherwise you'll end up with two clusters.

### 4.2 Create the Cloudprem namespace and secrets

By convention the namespace is `cloudprem-<username>` (e.g. `cloudprem-lahoucine`). Substitute below.

```bash
NS=cloudprem-lahoucine

kubectl create namespace $NS
kubectl config set-context --current --namespace=$NS

# API key secret (namespace-scoped — separate from the one in the datadog ns)
kubectl create secret generic datadog-secret \
  --from-literal api-key=$DD_API_KEY

# Metastore connection string for RDS Postgres
kubectl create secret generic cloudprem-metastore-uri \
  --from-literal "QW_METASTORE_URI=postgres://cloudprem:<db-password>@<DatabaseEndpoint>:5432/cloudprem"
```

### 4.3 Configure values and install the chart

In the CloudPrem repo, copy and edit the values template:

```bash
cd ../CloudPrem
cp datadog/cp-values.yaml.example datadog/cp-values.yaml
```

Update `cp-values.yaml` with the namespace, `IRSARoleName`, and `S3BucketName` from your CFN outputs. Then install:

```bash
helm upgrade --install cp datadog/cloudprem -f datadog/cp-values.yaml -n $NS
```

This deploys the Cloudprem components — indexer, searcher, control plane, metastore, and janitor.

### 4.4 Point the OPW pipeline at Cloudprem

In the Datadog UI, open your Observability Pipeline (the one created in Prerequisites) and add or update the destination to point at the Cloudprem indexer service in-cluster:

```
http://cp-cloudprem-indexer.<your-cloudprem-namespace>.svc.cluster.local:7280
```

If your pipeline parameterizes that URL with a placeholder like `${DESTINATION_CLOUDPREM_ENDPOINT_URL}`, add the corresponding `DD_OP_*` env var to [opw-values.yaml](opw-values.yaml) (a commented hint is already in the file), then `helm upgrade opw ...` to push it.

### 4.5 Verify Cloudprem

After all pods in the `cloudprem-*` namespace are ready, hit the search API directly from inside the cluster:

```bash
kubectl exec -n $NS -it cp-cloudprem-searcher-0 -- \
  curl -s 'http://localhost:7280/api/v1/datadog/search?query='
```

A JSON response (even empty) confirms the indexer is reachable and the metastore connection is healthy. Once OPW starts forwarding traffic, the same query (with `query=*` or a real keyword) will return ingested log records.

## 5. Deploy the DatadogAgent CR

```bash
kubectl apply -f datadog/datadog.yaml
```

This creates:

- `datadog-cluster-agent` (Deployment)
- `datadog-agent` (DaemonSet, one pod per node)

Verify all agent pods are `2/2 Running`:

```bash
kubectl get pods -n datadog -l agent.datadoghq.com/component=agent
```

If one pod is stuck `Pending` with `Too many pods`, the node has hit its VPC CNI pod limit (small instance types like `t3.medium` cap around 17 pods). Either increase the instance type, enable [VPC CNI prefix delegation](https://docs.aws.amazon.com/eks/latest/userguide/cni-increase-ip-addresses.html), or remove other workloads from that node.

## 6. APM single-step instrumentation

[datadog.yaml](datadog.yaml) enables auto-injection of the Datadog tracer (Python + JS) into pods in the `dev` and `prod` namespaces via the admission controller:

```yaml
features:
  apm:
    instrumentation:
      enabled: true
      targets:
        - name: default-target
          namespaceSelector:
            matchNames: [prod, dev]
          ddTraceVersions:
            python: "4"
            js: "5"
```

For existing pods, roll the deployments so the admission webhook can inject the tracer init containers:

```bash
kubectl rollout restart deploy -n dev
kubectl rollout restart deploy -n prod
```

Verify injection on one pod:

```bash
kubectl get pod -n dev -l app=lahoucine-app \
  -o jsonpath='{.items[0].spec.initContainers[*].name}{"\n"}'
# Expect: datadog-lib-python-init datadog-lib-js-init datadog-init-apm-inject
```

The same `targets[0]` block also injects RUM environment variables (`DD_RUM_APPLICATION_ID`, `DD_RUM_CLIENT_TOKEN`, etc.) into application containers. Rotate the secrets in [datadog.yaml](datadog.yaml) before committing this file to a public repo.

## 7. End-to-end verification

**Logs reach OPW:**

```bash
kubectl exec -n datadog ds/datadog-agent -c agent -- \
  agent status | sed -n '/Logs Agent/,/Errors:/p'
```

`BytesSent` should be climbing and there should be no `BytesDropped` against the OPW destination.

**Logs reach Cloudprem:** check OPW component metrics in the Datadog UI under the Observability Pipelines view, read OPW's own logs, or hit the searcher directly:

```bash
kubectl logs -n datadog opw-observability-pipelines-worker-0 --tail=50
kubectl exec -n <cloudprem-ns> -it cp-cloudprem-searcher-0 -- \
  curl -s 'http://localhost:7280/api/v1/datadog/search?query=*' | head
```

**Metrics + APM reach Datadog SaaS:** open the Datadog UI and look for:

- Infrastructure host map showing the `lahoucine-cluster` nodes
- APM service list showing `lahoucine-app` (and the frontend) emitting traces

## Updating

After editing [datadog.yaml](datadog.yaml):

```bash
kubectl apply -f datadog/datadog.yaml
kubectl rollout restart -n datadog ds/datadog-agent
kubectl rollout restart -n datadog deploy/datadog-cluster-agent
```

After editing [opw-values.yaml](opw-values.yaml):

```bash
helm upgrade opw -n datadog \
  -f datadog/opw-values.yaml \
  --set datadog.apiKey=$DD_API_KEY \
  --set datadog.pipelineId=$DD_PIPELINE_ID \
  datadog/observability-pipelines-worker
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Agent logs: `Could not send payload: ... opw-observability-pipelines-worker.datadog.svc.cluster.local:8282` | OPW pod isn't listening on 8282 | Check OPW logs for `Missing configuration option`; add the matching `DD_OP_*` env var to [opw-values.yaml](opw-values.yaml) |
| OPW logs: `Missing configuration option for identifier: <NAME>` | Pipeline placeholder is unset | Add `DD_OP_<NAME>` env var to [opw-values.yaml](opw-values.yaml) and `helm upgrade` |
| Agent pod stuck `Pending` (`Too many pods`) | Node hit CNI pod limit | Larger instance type or enable prefix delegation |
| No traces from app pods | Admission webhook didn't inject | Confirm pod has `datadog-lib-*-init` init containers; if not, the pod was created before the agent was installed — roll the deployment |
| `clusterName` shows the wrong value in the UI | Stale `clusterName` in [datadog.yaml](datadog.yaml) | Update `global.clusterName` and re-apply |
| Cloudprem searcher returns 5xx / no results | Metastore secret wrong, or IRSA role missing S3 permissions | Verify `QW_METASTORE_URI` resolves to RDS and `IRSARoleName` from the Cloudprem CFN outputs is set on `serviceAccount.eksRoleName` in `cp-values.yaml` |
| OPW destination `cp-cloudprem-indexer.<ns>...` is `Connection refused` | Cloudprem indexer pods aren't ready, or the OPW pipeline destination URL targets the wrong namespace | `kubectl get pods -n <cloudprem-ns>` and update the destination URL in the OPW pipeline UI to match the actual namespace |

## Uninstall

```bash
# Cloudprem (in its own namespace)
helm uninstall cp -n <cloudprem-ns>
kubectl delete secret cloudprem-metastore-uri -n <cloudprem-ns>
kubectl delete secret datadog-secret           -n <cloudprem-ns>
kubectl delete namespace <cloudprem-ns>
# Then delete the Cloudprem CFN stack (RDS + S3 + IRSA) from the AWS console.

# DatadogAgent CR (removes the agent + cluster agent)
kubectl delete -f datadog/datadog.yaml

# OPW
helm uninstall opw -n datadog

# Operator
helm uninstall datadog-operator -n datadog

# Secret + namespace
kubectl delete secret datadog-secret -n datadog
kubectl delete namespace datadog
```
