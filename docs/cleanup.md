# Cleanup

## Clean up in dependency order

First decide what must be retained: approved releases, scan and evaluation evidence, database snapshots, audit records and Terraform state. Use an explicit retained-resource list. Do not use a shared-bucket wildcard deletion.

1. Pause Argo CD reconciliation for the disposable applications. Disable scheduled workflows and new model evaluations. Wait for running jobs to finish or cancel the exact disposable job.
2. Stop load generators and remove temporary application keys and tool permissions.
3. Remove this stack's HTTPRoutes while AWS Load Balancer Controller and ExternalDNS are running. Wait for its DNS and ownership records to disappear, then remove its Gateway and wait for its ALB and target groups to disappear. Follow Platform addresses for the scoped commands. Keep the existing hosted zone and wildcard certificate.
4. Remove assistant, gateway and model workloads. Verify no Pod still depends on the stores or model volumes.
5. Stop the managed MLflow tracking server if it is not needed, or delete it only under the agreed retention plan. Preserve its artifact bucket when evidence must be retained.
6. Remove the dedicated controllers after their resources are cleaned up. Use the operator session for the remaining teardown.
7. Snapshot RDS as required, verify the snapshot and obtain the documented teardown authorization before changing deletion protection. Remove the dedicated database and Redis resources only after their clients stop.
8. Review Terraform's destroy plan from the same local project directory used to create the resources. Check every retained resource, dependency and account-specific name before applying it. Keep terraform.tfstate and its backup until cleanup is verified, and preserve encryption keys needed to read retained data.
9. Inventory remaining GPU/CPU instances, EBS volumes, load balancers, NAT gateways, interface endpoints, RDS/Redis resources, snapshots, ECR images, buckets, logs and MLflow resources. Confirm no unintended recurring compute remains.

```bash
kubectl get gateway,httproute -A
kubectl get pvc -A
aws sagemaker list-processing-jobs --region us-east-1 --status-equals InProgress
aws sagemaker list-mlflow-tracking-servers --region us-east-1
python plan_cleanup.py --output evidence/teardown.plan
terraform -chdir=infra show ../evidence/teardown.plan
```

The helper prepares a targeted deletion plan and a retained-resource report. It preserves S3 data and bucket controls, ECR images, encryption keys, CloudWatch logs and model-registry groups, and rejects any plan that would delete them. It does not apply the plan. Review both files, then apply with terraform -chdir=infra apply ../evidence/teardown.plan. If your inputs are outside infra/terraform.tfvars, pass the same private file with --var-file. If only retained resources remain, the helper reports that no plan is needed. Keep Terraform state through cleanup and afterward for the retained resources.

Before deleting RDS, set database_deletion_protection to false in your private Terraform inputs and apply that change. The default retains a final database snapshot. Set retain_final_database_snapshot to false only when the database contains disposable test data and its removal is approved. A retained encrypted snapshot requires its KMS key to remain usable.

For another run of the same lab, set final_database_snapshot_identifier to a new name in your private inputs before applying the foundation. RDS cannot create a second final snapshot with an existing name. Keep earlier snapshots and their encryption keys.

Storage volumes with the Retain policy survive deletion of their Kubernetes claims. Record the exact volume IDs and remove approved disposable volumes after they detach. Versioned S3 buckets and ECR repositories also remain until their approved contents have been removed. Keep test evidence locally before removing its cloud copies.


## Confirm cleanup and remaining charges

Check the resource list in the reviewed destroy plan and the tagged resources in AWS. Confirm that disposable GPU and CPU instances, load balancers, NAT gateways, database/cache instances and MLflow compute are gone. Check retained volumes, snapshots, buckets, logs and ECR images separately; they can still create charges.

Record any resource intentionally retained, its owner and why it remains. Review Cost Explorer again after billing data arrives. Keep the local Terraform state and cleanup evidence until the resource check is complete.
