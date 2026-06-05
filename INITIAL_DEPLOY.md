# Initial Deploy

End-to-end first-time setup for the Lahoucine dog-breeds app on EKS, with the Datadog stack and CloudPrem. After this, day-to-day deploys go through the GitHub Actions workflows.

All commands assume **eu-west-2 (London)** and **AWS account `369042512949`**.

## 0. Prerequisites

Local tools:

- `aws` (CLI v2)
- `kubectl`
- `helm` (v3)
- `eksctl` v0.180+
- `docker`
- `gh` (GitHub CLI) — optional, for triggering workflows

Accounts and access:

- AWS SSO access to account `369042512949`
- A Datadog account with API key + an Observability Pipelines pipeline ID (for CloudPrem)
- The domain `mcse-dogwiki.com` resolvable via the DNS provider of your choice (or remove the host rules from [k8s/ingress.yaml](k8s/ingress.yaml))

## 1. Authenticate via AWS SSO

**Don't** use the long-lived `lahoucine_cli` IAM user — it's blocked by the Datadog org SCP. Use SSO temporary credentials.

```bash
# Option A: paste the 3 exports from the SSO portal → account → "Command line or programmatic access"
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...

# Option B: aws-vault profile (recommended per Datadog wiki)
aws-vault exec sso-tse-sandbox-account-admin -- aws sts get-caller-identity
# Then prefix every aws/kubectl/helm/eksctl command with: aws-vault exec sso-tse-sandbox-account-admin --

export AWS_DEFAULT_REGION=eu-west-2

# Verify the identity is an assumed-role, NOT user/lahoucine_cli
aws sts get-caller-identity
```

## 2. Deploy the base CloudFormation stack

Creates the VPC, EKS cluster (k8s 1.34, `SupportType: STANDARD`), node group, OIDC provider, EBS CSI driver addon, and the app IRSA role. The S3 bucket for dog photos is referenced by name and lives outside the stack.

```bash
aws cloudformation deploy \
  --stack-name lahoucine-stack-1 \
  --template-file cloudformation/stack.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    Creator=lahoucine.elhaouri \
    Team=pre-sales-engineering \
  --tags \
    creator=lahoucine.elhaouri \
    team=pre-sales-engineering \
    ttl=2026-09-05 \
    purpose='Internal training'
```

The required SCP knobs are baked into the template: `UpgradePolicy.SupportType: STANDARD` plus explicit lowercase `creator` / `team` tags on the EKS Cluster and NodeGroup. Stack tags propagate to all other resources.

**Takes ~15–20 min.** Watch progress:

```bash
aws cloudformation describe-stacks --stack-name lahoucine-stack-1 \
  --query 'Stacks[0].StackStatus' --output text
```

Grab the outputs you'll need below:

```bash
aws cloudformation describe-stacks --stack-name lahoucine-stack-1 \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table
```

## 3. Configure kubectl

```bash
aws eks update-kubeconfig --name lahoucine-cluster
kubectl get nodes   # expect 2 t3.medium nodes Ready
```

## 4. Install the AWS Load Balancer Controller

The IAM policy is vendored at [k8s/alb-controller/iam_policy.json](k8s/alb-controller/iam_policy.json) so you don't have to curl it at deploy time.

```bash
# 4.1 IAM policy
aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy-lahoucine \
  --policy-document file://k8s/alb-controller/iam_policy.json \
  --tags \
    Key=creator,Value=lahoucine.elhaouri \
    Key=team,Value=pre-sales-engineering \
    Key=ttl,Value=2026-09-05 \
    Key=purpose,Value='Internal training'

# 4.2 IRSA service account (eksctl wires up the trust policy for us)
eksctl create iamserviceaccount \
  --cluster=lahoucine-cluster \
  --namespace=kube-system \
  --name=aws-load-balancer-controller \
  --attach-policy-arn=arn:aws:iam::369042512949:policy/AWSLoadBalancerControllerIAMPolicy-lahoucine \
  --override-existing-serviceaccounts \
  --region eu-west-2 \
  --approve

# 4.3 Helm install the controller
VPC_ID=$(aws cloudformation describe-stacks --stack-name lahoucine-stack-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`VPCId`].OutputValue' --output text)

helm repo add eks https://aws.github.io/eks-charts
helm repo update eks
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=lahoucine-cluster \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set region=eu-west-2 \
  --set vpcId=$VPC_ID \
  --version 1.14.0

# Verify (expect 2/2 ready)
kubectl get deploy -n kube-system aws-load-balancer-controller
```

## 5. Create the ECR repos

```bash
# Pass tags inline — shell variable expansion strips the quotes around values that contain spaces.
for REPO in lahoucine-flask lahoucine-app-frontend; do
  aws ecr create-repository --repository-name $REPO --tags \
    Key=creator,Value=lahoucine.elhaouri \
    Key=team,Value=pre-sales-engineering \
    Key=ttl,Value=2026-09-05 \
    'Key=purpose,Value=Internal training'
done
```

## 6. (Optional) Re-issue the ACM certificate

The cert ARN referenced in [k8s/ingress.yaml:11](k8s/ingress.yaml#L11) needs to be valid in eu-west-2 for HTTPS to work. If it's been wiped:

```bash
aws acm request-certificate \
  --domain-name mcse-dogwiki.com \
  --subject-alternative-names '*.mcse-dogwiki.com' \
  --validation-method DNS \
  --tags Key=creator,Value=lahoucine.elhaouri Key=team,Value=pre-sales-engineering Key=ttl,Value=2026-09-05 Key=purpose,Value='Internal training'
```

Add the DNS validation CNAME records shown by:

```bash
aws acm describe-certificate --certificate-arn <ARN> \
  --query 'Certificate.DomainValidationOptions[].ResourceRecord'
```

When the cert reaches `ISSUED`, update [k8s/ingress.yaml:11](k8s/ingress.yaml#L11) to the new ARN. If you don't need HTTPS for first boot, remove the `certificate-arn`, `ssl-redirect`, and `listen-ports`/HTTPS entries from the ingress.

## 7. Update your IP in the ingress allowlist

The ALB is restricted to specific source IPs via `alb.ingress.kubernetes.io/inbound-cidrs` on [k8s/ingress.yaml:12](k8s/ingress.yaml#L12). Add yours:

```bash
curl -s https://checkip.amazonaws.com    # your public IP
```

Edit the comma-separated list in [k8s/ingress.yaml:12](k8s/ingress.yaml#L12) and append `, <your-ip>/32`.

## 8. Configure GitHub Actions

In your repo → **Settings → Secrets and variables → Actions**:

**Secrets:**

| Name | Value |
|---|---|
| `AWS_ROLE_ARN` | ARN of an IAM role trusted by GH Actions OIDC. Must be SCP-allowed (an SSO-aligned role, not the IAM user). |
| `DD_API_KEY` | Datadog API key. |
| `CLOUDPREM_DB_PASSWORD` | RDS master password (min 8 chars). |

**Variables:**

| Name | Value |
|---|---|
| `DD_PIPELINE_ID` | Observability Pipelines pipeline ID from the Datadog UI. |

## 9. First app deploy (pushes to `main` from here on)

```bash
git add -A
git commit -m "first deploy"
git push origin main
```

[.github/workflows/deploy.yaml](.github/workflows/deploy.yaml) does the rest:

1. Detects changes in backend / frontend paths.
2. Builds + pushes ECR images.
3. Creates the `prod` namespace.
4. Applies [k8s/](k8s/) manifests.
5. Rolls the deployments to the new image tag.

Watch:

```bash
gh run watch
```

Then:

```bash
kubectl get pods -n prod
kubectl get ingress -n prod                # ALB hostname in the ADDRESS column
```

## 10. Deploy the Datadog stack + CloudPrem

```bash
gh workflow run cloudprem.yaml
gh run watch
```

[.github/workflows/cloudprem.yaml](.github/workflows/cloudprem.yaml) deploys:

1. Cloudprem infra CFN stack (`lahoucine-cloudprem-infra`) — RDS metastore + S3 splits bucket + IRSA role.
2. Datadog operator (helm).
3. The `DatadogAgent` CR from [datadog/datadog.yaml](datadog/datadog.yaml).
4. OPW (helm) with your API key and pipeline ID.
5. Namespace + secrets for Cloudprem.
6. The `cloudprem` helm chart from the Datadog public registry.
7. A searcher smoke test.

For details, see [datadog/README.md](datadog/README.md).

## 11. Seed the database (one-time)

Insert rows that match the 3 photos already in the S3 bucket:

```bash
PG=$(kubectl get pod -n prod -l app=postgres -o jsonpath='{.items[0].metadata.name}')
kubectl cp k8s/seed-dogs.sql prod/$PG:/tmp/seed.sql
kubectl exec -n prod $PG -- psql -U postgres -d dogsdb -f /tmp/seed.sql
kubectl exec -n prod $PG -- psql -U postgres -d dogsdb -c "SELECT id, breed FROM dogs;"
```

## 12. Verify end-to-end

```bash
# IRSA on the app pod
kubectl exec -n prod deploy/lahoucine-app -- python3 -c \
  'import boto3; print(boto3.client("sts").get_caller_identity()["Arn"])'
# expect: ...:assumed-role/lahoucine-cluster-app-s3/...

# Logs flowing through OPW
kubectl exec -n datadog ds/datadog-agent -c agent -- \
  agent status | sed -n '/Logs Agent/,/Errors:/p'

# CloudPrem searching
kubectl exec -n cloudprem cp-cloudprem-searcher-0 -- \
  curl -s 'http://localhost:7280/api/v1/datadog/search?query=*' | head

# Open the app
curl -k https://$(kubectl get ingress -n prod lahoucine-app-ingress \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')/
```

If you reach this point everything is green — the rest is iterating via `git push`.

## Tear-down

```bash
# 1. App namespace
kubectl delete namespace prod cloudprem datadog || true

# 2. ALB controller
helm uninstall aws-load-balancer-controller -n kube-system
eksctl delete iamserviceaccount \
  --cluster=lahoucine-cluster --namespace=kube-system \
  --name=aws-load-balancer-controller --region=eu-west-2
aws iam delete-policy \
  --policy-arn arn:aws:iam::369042512949:policy/AWSLoadBalancerControllerIAMPolicy-lahoucine

# 3. CFN stacks (Cloudprem first because it imports from the base)
aws cloudformation delete-stack --stack-name lahoucine-cloudprem-infra
aws cloudformation wait stack-delete-complete --stack-name lahoucine-cloudprem-infra
aws cloudformation delete-stack --stack-name lahoucine-stack-1
aws cloudformation wait stack-delete-complete --stack-name lahoucine-stack-1

# 4. ECR repos
aws ecr delete-repository --repository-name lahoucine-flask         --force
aws ecr delete-repository --repository-name lahoucine-app-frontend  --force

# The S3 bucket lahoucine-cluster-dog-photos-369042512949 survives by design.
# Delete manually if you want it gone:
# aws s3 rb s3://lahoucine-cluster-dog-photos-369042512949 --force
```
