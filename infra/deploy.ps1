<#
.SYNOPSIS
  CPM Ground App - AWS deploy runbook (free-tier shape: EC2 + RDS + S3 + CloudFront).
  Account: 439869877669, region ap-south-1, profile cpm-ground-app-deploy.

.USAGE
  .\deploy.ps1 -Stage network   -DryRun   # preview only, creates nothing
  .\deploy.ps1 -Stage network             # VPC, RDS, S3
  .\deploy.ps1 -Stage upload-src          # zip backend/, upload to S3 (needed before first compute deploy and every redeploy)
  .\deploy.ps1 -Stage compute             # the EC2 instance
  .\deploy.ps1 -Stage frontend            # CloudFront + S3, also uploads app.html
  .\deploy.ps1 -Stage publish-frontend    # re-upload app.html + invalidate cache (after any app.html edit)
  .\deploy.ps1 -Stage redeploy-backend    # upload-src + bump compute stack to force EC2 to rebuild+restart

.NOTES
  No Docker/Terraform needed locally - the backend image is built ON the EC2
  instance itself from the uploaded source zip.
#>
param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("network", "upload-src", "compute", "frontend", "publish-frontend", "redeploy-backend", "tighten-cors")]
  [string]$Stage,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Region = "ap-south-1"
$Profile = "cpm-ground-app-deploy"
$ProjectName = "cpm-ground-app"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$AwsArgs = @("--region", $Region, "--profile", $Profile)
$SecretsFile = Join-Path $PSScriptRoot ".secrets.json"   # gitignored - generated passwords live here only

function Get-OrCreateSecrets {
  if (Test-Path $SecretsFile) { return (Get-Content $SecretsFile | ConvertFrom-Json) }
  Add-Type -AssemblyName System.Web
  $s = [PSCustomObject]@{
    DBPassword = [System.Web.Security.Membership]::GeneratePassword(20, 4) -replace '["`$\\]', '#'
    JwtSecret  = [System.Web.Security.Membership]::GeneratePassword(48, 8) -replace '["`$\\]', '#'
  }
  $s | ConvertTo-Json | Set-Content $SecretsFile
  Write-Output "Generated new DB password + JWT secret -> $SecretsFile (keep this out of git)."
  return $s
}

function Deploy-Stack {
  param([string]$StackName, [string]$TemplateFile, [string[]]$ParamOverrides)
  $templatePath = Join-Path $PSScriptRoot $TemplateFile
  $prevPref = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  $status = aws cloudformation describe-stacks --stack-name $StackName --query "Stacks[0].StackStatus" --output text @AwsArgs 2>$null
  $ErrorActionPreference = $prevPref
  if ($status -eq "ROLLBACK_COMPLETE") {
    Write-Output "--- $StackName is in ROLLBACK_COMPLETE from a prior failed attempt - deleting it first ---"
    aws cloudformation delete-stack --stack-name $StackName @AwsArgs
    aws cloudformation wait stack-delete-complete --stack-name $StackName @AwsArgs
  }
  if ($DryRun) {
    Write-Output "--- DRY RUN: change set for $StackName (nothing will be created) ---"
    aws cloudformation deploy --stack-name $StackName --template-file $templatePath `
      --parameter-overrides $ParamOverrides --capabilities CAPABILITY_NAMED_IAM `
      --no-execute-changeset @AwsArgs
    $csName = aws cloudformation list-change-sets --stack-name $StackName --query "Summaries[-1].ChangeSetName" --output text @AwsArgs
    aws cloudformation describe-change-set --stack-name $StackName --change-set-name $csName `
      --query "Changes[].ResourceChange.{Action:Action,Type:ResourceType,Id:LogicalResourceId}" --output table @AwsArgs
    Write-Output "Review the table above. Re-run the same command WITHOUT -DryRun to apply."
    return
  }
  Write-Output "--- Deploying $StackName from $TemplateFile ---"
  aws cloudformation deploy --stack-name $StackName --template-file $templatePath `
    --parameter-overrides $ParamOverrides --capabilities CAPABILITY_NAMED_IAM @AwsArgs
  if ($LASTEXITCODE -ne 0) { throw "Deploying $StackName failed (exit $LASTEXITCODE) - stopping here, not proceeding to later stages." }
}

function Get-Output {
  param([string]$StackName, [string]$Key)
  aws cloudformation describe-stacks --stack-name $StackName `
    --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue" --output text @AwsArgs
}

switch ($Stage) {

  "network" {
    $secrets = Get-OrCreateSecrets
    Deploy-Stack -StackName "$ProjectName-network" -TemplateFile "network.yaml" -ParamOverrides @(
      "ProjectName=$ProjectName",
      "DBMasterPassword=$($secrets.DBPassword)"
    )
  }

  "upload-src" {
    $bucket = Get-Output "$ProjectName-network" "BucketName"
    if (-not $bucket) { throw "Run '.\deploy.ps1 -Stage network' first." }
    $backendDir = Join-Path $RepoRoot "backend"
    $staging = Join-Path $env:TEMP "cpm-backend-src"
    $zipPath = Join-Path $env:TEMP "cpm-backend-src.zip"
    if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    New-Item -ItemType Directory -Path $staging | Out-Null
    Copy-Item "$backendDir\*" $staging -Recurse -Exclude @(".venv", "data")
    Get-ChildItem $staging -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    Compress-Archive -Path "$staging\*" -DestinationPath $zipPath -Force
    aws s3 cp $zipPath "s3://$bucket/src/backend-src.zip" @AwsArgs
    Write-Output "Uploaded backend source to s3://$bucket/src/backend-src.zip"
  }

  "compute" {
    $secrets = Get-OrCreateSecrets
    $bucket = Get-Output "$ProjectName-network" "BucketName"
    $subnet = Get-Output "$ProjectName-network" "PublicSubnetId"
    $sg = Get-Output "$ProjectName-network" "Ec2SecurityGroupId"
    $dbHost = Get-Output "$ProjectName-network" "RDSEndpointAddress"
    $dbPort = Get-Output "$ProjectName-network" "RDSEndpointPort"
    $dbName = Get-Output "$ProjectName-network" "DBName"
    $dbUser = Get-Output "$ProjectName-network" "DBMasterUsername"
    if (-not $bucket) { throw "Run '.\deploy.ps1 -Stage network' first." }
    Deploy-Stack -StackName "$ProjectName-compute" -TemplateFile "compute.yaml" -ParamOverrides @(
      "ProjectName=$ProjectName",
      "PublicSubnetId=$subnet",
      "Ec2SecurityGroupId=$sg",
      "BucketName=$bucket",
      "RDSEndpointAddress=$dbHost",
      "RDSEndpointPort=$dbPort",
      "DBName=$dbName",
      "DBMasterUsername=$dbUser",
      "DBMasterPassword=$($secrets.DBPassword)",
      "JwtSecret=$($secrets.JwtSecret)",
      "SourceObjectVersion=$(Get-Date -Format o)"
    )
    if (-not $DryRun) {
      $ip = Get-Output "$ProjectName-compute" "PublicIp"
      Write-Output "Backend instance public IP: $ip (takes ~1-3 min after stack completes for user-data to finish building+starting the container)"
    }
  }

  "frontend" {
    $ip = Get-Output "$ProjectName-compute" "PublicIp"
    if (-not $ip) { throw "Run '.\deploy.ps1 -Stage compute' first." }
    Deploy-Stack -StackName "$ProjectName-frontend" -TemplateFile "frontend.yaml" -ParamOverrides @(
      "ProjectName=$ProjectName",
      "BackendPublicIp=$ip"
    )
    if (-not $DryRun) { & $PSCommandPath -Stage publish-frontend }
  }

  "publish-frontend" {
    $bucket = Get-Output "$ProjectName-frontend" "FrontendBucketName"
    $distId = Get-Output "$ProjectName-frontend" "DistributionId"
    if (-not $bucket) { throw "Run '.\deploy.ps1 -Stage frontend' first." }
    aws s3 cp (Join-Path $RepoRoot "app.html") "s3://$bucket/index.html" @AwsArgs
    aws cloudfront create-invalidation --distribution-id $distId --paths "/*" --profile $Profile | Out-Null
    $url = Get-Output "$ProjectName-frontend" "AppUrl"
    Write-Output "App live at: $url"
  }

  "redeploy-backend" {
    & $PSCommandPath -Stage upload-src
    & $PSCommandPath -Stage compute
  }

  "tighten-cors" {
    # Not needed in this shape - frontend and API share one CloudFront domain (same-origin),
    # so CPM_CORS_ORIGINS never has to change from its default. Kept as a no-op for parity
    # with earlier notes; safe to ignore.
    Write-Output "No-op: app.html and the API are same-origin behind CloudFront, CORS isn't in play."
  }
}
