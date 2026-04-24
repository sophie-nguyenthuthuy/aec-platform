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
