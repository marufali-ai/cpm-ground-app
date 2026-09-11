# One-time: create a deploy identity for this app

The `default` CLI profile (`text-audit`, account `475257136714`) cannot provision
this infrastructure — it lacks `cloudformation:*` and can't even list its own IAM
policies, so it can't grant itself more access either. Someone with admin/root
access to account `475257136714` needs to run the following **once**, from the AWS
Console (CloudShell is easiest) or a CLI session already authenticated as an admin —
**not** the `text-audit` profile:

```bash
# 1. Create the IAM user dedicated to this app's deployment
aws iam create-user --user-name cpm-ground-app-deploy

# 2. Attach the scoped policy (this directory)
aws iam put-user-policy \
  --user-name cpm-ground-app-deploy \
  --policy-name cpm-ground-app-deploy \
  --policy-document file://cpm-ground-app-deploy-policy.json

# 3. Create an access key for it
aws iam create-access-key --user-name cpm-ground-app-deploy
```

Take the `AccessKeyId`/`SecretAccessKey` from step 3 and add a new profile locally:

```powershell
aws configure --profile cpm-ground-app-deploy
# region: ap-south-1, output: json
```

Then tell me to use profile `cpm-ground-app-deploy` (or update `$Profile` in
`infra/deploy.ps1`) and we can proceed with `-Stage data -DryRun`.

## What the policy grants and why

Scoped by resource-name prefix (`cpm-ground-app-*`) everywhere the service supports
it — S3 buckets, ECR repo, CodeBuild project, Secrets Manager secrets, IAM roles —
so this identity cannot touch unrelated resources already in the account (including
whatever `text-audit` or other credentials are used for). Full access is granted
only for services where AWS doesn't support that kind of scoping well pre-creation
(CloudFormation, EC2/VPC, RDS, App Runner, CloudFront) — normal for a
per-project deploy user, but worth knowing before approving it.

`iam:PassRole` is limited to roles named `cpm-ground-app-*`, which is what stops
this identity from being used to grant itself (or anything else) broader access
through an unrelated role.

## Revoking it later

```bash
aws iam delete-access-key --user-name cpm-ground-app-deploy --access-key-id <id>
aws iam delete-user-policy --user-name cpm-ground-app-deploy --policy-name cpm-ground-app-deploy
aws iam delete-user --user-name cpm-ground-app-deploy
```
