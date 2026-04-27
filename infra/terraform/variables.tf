variable "region" {
  type        = string
  default     = "ap-southeast-1"
  description = "AWS region (Singapore default for Vietnam latency)."
}

variable "environment" {
  type        = string
  description = "Deployment environment (e.g. dev, staging, prod)."
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "az_count" {
  type    = number
  default = 2
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "db_storage_gb" {
  type    = number
  default = 50
}

variable "db_username" {
  type    = string
  default = "aec"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "api_image" {
  type        = string
  description = "ECR image URI for the api container."
}

variable "web_image" {
  type        = string
  description = "ECR image URI for the web container."
}

variable "worker_image" {
  type        = string
  description = "ECR image URI for the worker container."
}

variable "domain_name" {
  type        = string
  description = "Apex domain, e.g. aec-platform.vn"
}

# GitHub Actions OIDC — used by `github_oidc.tf` to scope the trust policy
# to a single repo (and optionally branch) so a leaked workflow file in a
# fork can't assume the deploy role.
variable "github_owner" {
  type        = string
  default     = "sophie-nguyenthuthuy"
  description = "GitHub user/org that owns the repo allowed to assume AWS."
}

variable "github_repo" {
  type        = string
  default     = "aec-platform"
  description = "GitHub repo allowed to assume AWS via OIDC."
}

variable "github_oidc_branch" {
  type        = string
  default     = "main"
  description = "Branch ref allowed to deploy. Use '*' to allow all refs."
}
