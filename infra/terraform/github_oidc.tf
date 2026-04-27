# GitHub Actions OIDC trust setup for CI/CD into AWS.
#
# What this provisions
# --------------------
# 1. The GitHub OIDC provider in this AWS account (token.actions.github.com).
#    There can be only one per account — if you've set this up via another
#    repo's terraform, comment out the `aws_iam_openid_connect_provider`
#    resource below and reference its ARN directly.
# 2. An IAM role (`aec-deploy`) that GitHub Actions can assume via OIDC.
#    Trust policy is locked to repo `var.github_owner/var.github_repo` and
#    (by default) branch `var.github_oidc_branch` — a leaked workflow file
#    in a fork or a feature branch can't assume this role.
# 3. Inline + managed policies covering exactly what `deploy.yml` does:
#    push images to ECR, register/update ECS task definitions, force a
#    service deployment, and read SSM params for runtime config.
#
# Bootstrap
# ---------
# After `terraform apply`, the role ARN is in `output.github_actions_role_arn`
# and the AWS account id is in `output.aws_account_id`. Wire both into
# GitHub repo secrets:
#
#   gh secret set AWS_DEPLOY_ROLE_ARN --body "$(terraform output -raw github_actions_role_arn)"
#   gh secret set AWS_ACCOUNT_ID      --body "$(terraform output -raw aws_account_id)"
#
# Then rename `.github/workflows/deploy.yml.disabled` → `deploy.yml`.

data "aws_caller_identity" "current" {}

# The OIDC provider thumbprint is GitHub's well-known root CA — see
# https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services
# Both thumbprints are listed because GitHub rotates them; including both
# means a rotation doesn't take down deploys.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]

  tags = {
    Name        = "github-actions-oidc"
    Environment = var.environment
  }
}

locals {
  github_repo_full = "${var.github_owner}/${var.github_repo}"
  # `*` means "any ref". A specific branch is `refs/heads/<branch>`. A tag
  # is `refs/tags/<tag>`. The trust policy uses `StringLike` so wildcards
  # in the value (e.g. `refs/heads/release/*`) work without policy changes.
  github_ref_pattern = (
    var.github_oidc_branch == "*"
    ? "*"
    : "refs/heads/${var.github_oidc_branch}"
  )
}

data "aws_iam_policy_document" "github_actions_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    # Audience must be exactly `sts.amazonaws.com` (set by
    # `aws-actions/configure-aws-credentials@v4`).
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Subject locks to the specific repo + ref. Without this, *any* GitHub
    # repo could mint tokens that pass the audience check.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${local.github_repo_full}:ref:${local.github_ref_pattern}"]
    }
  }
}

resource "aws_iam_role" "github_actions_deploy" {
  name               = "aec-deploy"
  description        = "Assumed by GitHub Actions in ${local.github_repo_full} for CI/CD deploys"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume.json
  max_session_duration = 3600

  tags = {
    Name        = "aec-deploy"
    Environment = var.environment
  }
}

# Permissions: only what `deploy.yml` needs. ECR push + ECS register/update +
# pass-role for the task execution role + read deploy-time SSM params.
data "aws_iam_policy_document" "github_actions_deploy" {
  statement {
    sid    = "EcrPush"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "EcsDeploy"
    effect = "Allow"
    actions = [
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeClusters",
      "ecs:ListServices",
      "ecs:ListTasks",
      "ecs:RegisterTaskDefinition",
      "ecs:UpdateService",
    ]
    resources = ["*"]
  }

  # ECS task definitions reference an execution role (and optionally a task
  # role); register-task-definition needs explicit pass-role for both.
  statement {
    sid       = "PassExecutionRoles"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::*:role/aec-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid    = "SsmRead"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]
    resources = ["arn:aws:ssm:${var.region}:*:parameter/aec/${var.environment}/*"]
  }

  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "logs:GetLogEvents",
    ]
    resources = ["arn:aws:logs:${var.region}:*:log-group:/aws/ecs/aec-*"]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy" {
  name   = "aec-deploy-policy"
  role   = aws_iam_role.github_actions_deploy.id
  policy = data.aws_iam_policy_document.github_actions_deploy.json
}
