# Lahoucine App - Dog Breeds on Kubernetes

A full-stack application for managing dog breeds with photos, running on Amazon EKS.

- **Backend**: Python Flask API with PostgreSQL and S3
- **Frontend**: React (Vite) served by Nginx
- **Infrastructure**: CloudFormation (VPC, EKS, S3, EBS CSI Driver) with AWS Load Balancer Controller

## Architecture

```
Internet
   |
   v
[ ALB Ingress ]
   |
   v
[ Nginx Frontend ] --/api/--> [ Flask API ] --> [ PostgreSQL ]
   (React SPA)                     |
                                   v
                              [ S3 Bucket ]
                            (dog photos)
```

## Prerequisites

- AWS CLI configured with appropriate permissions
- Docker
- kubectl
- Helm
- eksctl

## 1. Deploy Infrastructure (CloudFormation)

The CloudFormation stack creates: VPC (public/private subnets, NAT Gateway), S3 bucket, EKS cluster with node group, OIDC provider, and EBS CSI driver addon.

Deploy via the AWS Console:

1. Go to **CloudFormation** in the AWS Console (region: **eu-west-2**)
2. Click **Create stack** > **With new resources (standard)**
3. Select **Upload a template file** and upload `cloudformation/stack.yaml`
4. Set stack name to `lahoucine-cluster`
5. Review parameters and click **Next** through the pages
6. Check **I acknowledge that AWS CloudFormation might create IAM resources with custom names**
7. Click **Submit**

Or deploy via CLI:

```bash
aws cloudformation create-stack \
  --stack-name lahoucine-cluster \
  --template-body file://cloudformation/stack.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --region eu-west-2
```

Wait for the stack to complete (~15-20 minutes):

```bash
aws cloudformation wait stack-create-complete \
  --stack-name lahoucine-cluster \
  --region eu-west-2
```

Get the stack outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name lahoucine-cluster \
  --region eu-west-2 \
  --query "Stacks[0].Outputs" \
  --output table
```

## 2. Configure kubectl

```bash
aws eks update-kubeconfig \
  --name lahoucine-cluster \
  --region eu-west-2
```

Verify connectivity:

```bash
kubectl get nodes
```

Verify the EBS CSI driver is active (installed automatically by CloudFormation):

```bash
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-ebs-csi-driver
```

## 3. Install AWS Load Balancer Controller

Reference: https://docs.aws.amazon.com/eks/latest/userguide/lbc-helm.html

### 3.1 Create IAM policy

```bash
curl -O https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.14.1/docs/install/iam_policy.json

aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy-lahoucine \
  --policy-document file://iam_policy.json
```

### 3.2 Create IAM service account

```bash
eksctl create iamserviceaccount \
  --cluster=lahoucine-cluster \
  --namespace=kube-system \
  --name=aws-load-balancer-controller \
  --attach-policy-arn=arn:aws:iam::369042512949:policy/AWSLoadBalancerControllerIAMPolicy-lahoucine \
  --override-existing-serviceaccounts \
  --region eu-west-2 \
  --approve
```

Verify the service account was created:

```bash
kubectl get sa aws-load-balancer-controller -n kube-system
```

### 3.3 Install via Helm

```bash
helm repo add eks https://aws.github.io/eks-charts
helm repo update eks

helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=lahoucine-cluster \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set region=eu-west-2 \
  --set vpcId=vpc-09b7231e0487caf0a \
  --version 1.14.0
```

### 3.4 Verify

```bash
kubectl get deployment -n kube-system aws-load-balancer-controller
```

Expected: 2/2 replicas ready.

## 4. Create ECR Repositories

```bash
aws ecr create-repository --repository-name lahoucine-flask --region eu-west-2
aws ecr create-repository --repository-name lahoucine-app-frontend --region eu-west-2
```

Authenticate Docker with ECR:

```bash
aws ecr get-login-password --region eu-west-2 | \
  docker login --username AWS --password-stdin 369042512949.dkr.ecr.eu-west-2.amazonaws.com
```

## 5. Build and Push Images

Important: Use `--platform linux/amd64` since EKS nodes run on AMD64.

### Backend (Flask API)

```bash
docker build --platform linux/amd64 -t lahoucine-flask .

docker tag lahoucine-flask:latest \
  369042512949.dkr.ecr.eu-west-2.amazonaws.com/lahoucine-flask:latest

docker push 369042512949.dkr.ecr.eu-west-2.amazonaws.com/lahoucine-flask:latest
```

### Frontend (React)

```bash
cd frontend

docker build --platform linux/amd64 -t lahoucine-app-frontend .

docker tag lahoucine-app-frontend:latest \
  369042512949.dkr.ecr.eu-west-2.amazonaws.com/lahoucine-app-frontend:latest

docker push 369042512949.dkr.ecr.eu-west-2.amazonaws.com/lahoucine-app-frontend:latest

cd ..
```

## 6. Deploy to Kubernetes

Apply all manifests:

```bash
kubectl apply -f k8s/
```

Check that all pods are running:

```bash
kubectl get pods
```

Expected output:

```
NAME                                       READY   STATUS    RESTARTS   AGE
lahoucine-app-xxxxxxxxx-xxxxx              1/1     Running   0          ...
lahoucine-app-xxxxxxxxx-xxxxx              1/1     Running   0          ...
lahoucine-app-xxxxxxxxx-xxxxx              1/1     Running   0          ...
lahoucine-app-frontend-xxxxxxxxx-xxxxx     1/1     Running   0          ...
lahoucine-app-frontend-xxxxxxxxx-xxxxx     1/1     Running   0          ...
postgres-xxxxxxxxx-xxxxx                   1/1     Running   0          ...
```

## 7. Access the Application

Get the ALB URL:

```bash
kubectl get ingress lahoucine-app-ingress
```

The `ADDRESS` column shows the ALB hostname. Open it in your browser:

```
http://<ALB-ADDRESS>
```

It may take 1-2 minutes for the ALB to provision and become healthy.

## API Endpoints

| Method | Path         | Description                          |
|--------|--------------|--------------------------------------|
| GET    | /            | Welcome message                      |
| GET    | /health      | Health check                         |
| GET    | /dogs        | List all dog breeds                  |
| GET    | /dogs/:id    | Get a specific dog breed             |
| POST   | /dogs        | Add a new breed (multipart form)     |

### Example: Add a dog breed via curl

```bash
curl -X POST http://<ALB-ADDRESS>/api/dogs \
  -F "breed=Golden Retriever" \
  -F "description=Friendly and tolerant" \
  -F "photo=@golden.jpg"
```

### Example: List all breeds

```bash
curl http://<ALB-ADDRESS>/api/dogs
```

## Useful Commands

### Logs

```bash
# Flask API logs
kubectl logs -l app=lahoucine-app

# Frontend logs
kubectl logs -l app=lahoucine-app-frontend

# PostgreSQL logs
kubectl logs -l app=postgres
```

### Restart a deployment

```bash
kubectl rollout restart deployment lahoucine-app
kubectl rollout restart deployment lahoucine-app-frontend
```

### Redeploy after code changes

```bash
# Rebuild and push the image
docker build --platform linux/amd64 -t lahoucine-flask .
docker tag lahoucine-flask:latest 369042512949.dkr.ecr.eu-west-2.amazonaws.com/lahoucine-flask:latest
docker push 369042512949.dkr.ecr.eu-west-2.amazonaws.com/lahoucine-flask:latest

# Restart the deployment to pull the new image
kubectl rollout restart deployment lahoucine-app
```

### Connect to PostgreSQL

```bash
kubectl exec -it deployment/postgres -- psql -U postgres -d dogsdb
```

### Port-forward for local testing

```bash
# Frontend
kubectl port-forward svc/lahoucine-app-frontend 8080:80

# API directly
kubectl port-forward svc/lahoucine-app 8081:80
```

## Cleanup

### Delete Kubernetes resources

```bash
kubectl delete -f k8s/
```

### Uninstall ALB controller

```bash
helm uninstall aws-load-balancer-controller -n kube-system
eksctl delete iamserviceaccount \
  --cluster=lahoucine-cluster \
  --namespace=kube-system \
  --name=aws-load-balancer-controller \
  --region eu-west-2
aws iam delete-policy --policy-arn arn:aws:iam::369042512949:policy/AWSLoadBalancerControllerIAMPolicy-lahoucine
```

### Delete ECR repositories

```bash
aws ecr delete-repository --repository-name lahoucine-flask --force --region eu-west-2
aws ecr delete-repository --repository-name lahoucine-app-frontend --force --region eu-west-2
```

### Delete CloudFormation stack

```bash
aws cloudformation delete-stack --stack-name lahoucine-cluster --region eu-west-2
aws cloudformation wait stack-delete-complete --stack-name lahoucine-cluster --region eu-west-2
```
