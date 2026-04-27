output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "db_endpoint" {
  value     = aws_db_instance.main.address
  sensitive = true
}

output "redis_endpoint" {
  value     = aws_elasticache_replication_group.main.primary_endpoint_address
  sensitive = true
}

output "files_bucket" {
  value = aws_s3_bucket.files.bucket
}

output "cloudfront_domain" {
  value = aws_cloudfront_distribution.files.domain_name
}

output "ecs_cluster" {
  value = aws_ecs_cluster.main.name
}

# ---------- GitHub Actions OIDC ----------
# Wire these into repo secrets after `terraform apply`:
#   gh secret set AWS_DEPLOY_ROLE_ARN --body "$(terraform output -raw github_actions_role_arn)"
#   gh secret set AWS_ACCOUNT_ID      --body "$(terraform output -raw aws_account_id)"

output "github_actions_role_arn" {
  value       = aws_iam_role.github_actions_deploy.arn
  description = "ARN to set as GitHub repo secret AWS_DEPLOY_ROLE_ARN."
}

output "aws_account_id" {
  value       = data.aws_caller_identity.current.account_id
  description = "AWS account id; set as GitHub repo secret AWS_ACCOUNT_ID."
  sensitive   = true
}
