# CPM Ground App — AWS deployment (free-tier shape)

Account `439869877669`, region `ap-south-1`, CLI profile `cpm-ground-app-deploy` (a
scoped identity — see [iam-bootstrap/](iam-bootstrap/) for how it was created).

## Architecture

```
  Phone / browser ──HTTPS──▶ CloudFront (one domain, free *.cloudfront.net cert)
                               │
                    ┌──────────┴───────────┐
              default (/*)            /api/*
                    │                       │
                    ▼                       ▼
             S3 (app.html)          EC2 t3.micro (FastAPI in Docker,
             via Origin Access      security group only allows inbound
             Control, private       from CloudFront's IP range)
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                    RDS db.t4g.micro          S3 (evidence photos,
                    (private subnet)          same bucket, /evidence/ prefix)
```

One CloudFront domain serves both the app and the API (`/api/*` path routed to the
EC2 origin) — same-origin, so there's no CORS to configure, and mobile browsers get
the HTTPS "secure context" that camera/GPS access requires. No NAT gateway, no
custom domain, no Secrets Manager (a NoEcho CloudFormation parameter holds the DB
password and JWT secret instead — fine for a personal pilot, costs $0 instead of
~$1/mo, upgrade later if this becomes multi-user/production).

## Free Tier fit (12 months from account creation)

| Resource | Free tier allowance | This uses |
|---|---|---|
| EC2 | 750 hrs/mo t2/t3.micro | 1× t3.micro, 24/7 (~730 hrs) |
| RDS | 750 hrs/mo db.t2/t3/t4g.micro + 20GB | 1× db.t4g.micro, 20GB gp2 |
| S3 | 5GB standard storage | evidence photos + deploy source zips |
| CloudFront | 1TB out + 10M requests (Always Free, not just 12mo) | — |

Running a **second** instance of EC2 or RDS concurrently (even briefly, e.g. during
a blue/green swap) would exceed the free allowance for that month. Stick to one of
each.

## Deploy order

```powershell
cd infra
.\deploy.ps1 -Stage network   -DryRun    # preview first
.\deploy.ps1 -Stage network              # VPC, RDS, S3 (takes ~10 min, RDS is slow to create)
.\deploy.ps1 -Stage upload-src           # zips backend/, uploads to S3
.\deploy.ps1 -Stage compute              # launches the EC2 instance
.\deploy.ps1 -Stage frontend             # CloudFront + S3, uploads app.html, invalidates cache
```

`-DryRun` on `network` or `compute` previews a CloudFormation change set without
creating anything.

First deploy runs with `SeedOnStart=true` and `ExposeOtp=true` (needed until real
SMS delivery exists) — see [../backend/README.md](../backend/README.md) for the
demo accounts this seeds. After confirming login works, redeploy `compute` with
`SeedOnStart=false` in the parameter overrides so restarts stop reseeding demo data.

## After any code change

- **app.html only:** `.\deploy.ps1 -Stage publish-frontend`
- **backend only:** `.\deploy.ps1 -Stage redeploy-backend` (re-zips, re-uploads,
  bumps the compute stack so CloudFormation replaces the EC2 instance and its
  user-data reruns — the Elastic IP stays the same, so nothing downstream needs
  updating)

## Generated secrets

`.\deploy.ps1` writes `infra/.secrets.json` (gitignored) the first time it needs a
DB password / JWT secret, and reuses it on every later call — don't delete it
between `network` and `compute` runs or they'll disagree on the DB password.

## Not in this build (deliberately, matches backend/README.md)

- Real OTP/SMS delivery — vendor-code login is the only path that works for a real
  phone number today
- Alembic migrations — schema changes mean redeploying `compute` (fine for a pilot,
  not for one with real user data you can't lose)
- Cross-device stakeholder/CPM views wired to the API — still local-per-device in
  app.html

## Teardown

```powershell
aws cloudformation delete-stack --stack-name cpm-ground-app-frontend --region ap-south-1 --profile cpm-ground-app-deploy
aws cloudformation delete-stack --stack-name cpm-ground-app-compute   --region ap-south-1 --profile cpm-ground-app-deploy
aws cloudformation delete-stack --stack-name cpm-ground-app-network   --region ap-south-1 --profile cpm-ground-app-deploy
```

`network.yaml`'s RDS instance has `DeletionPolicy: Snapshot` — deleting that stack
leaves a final snapshot behind (small storage cost) instead of losing data silently.
