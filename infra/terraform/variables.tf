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
