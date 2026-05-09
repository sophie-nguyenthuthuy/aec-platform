# ECR repositories that the deploy pipeline (.github/workflows/deploy.yml)
# pushes to. One repo per service. Image scan-on-push catches CVEs at
# upload time; lifecycle policy prunes old image tags so the repo doesn't
# bloat to the GB scale that ECR's free tier won't carry.
#
# These names are referenced by `aws_ecs_task_definition.{api,web,worker}`
# via `var.api_image` / `var.web_image` / `var.worker_image`. Set those
# variables to the full ECR URI (e.g. via the deploy workflow).

locals {
  ecr_services = ["api", "web", "worker"]
}

resource "aws_ecr_repository" "service" {
  for_each = toset(local.ecr_services)

  name                 = "aec-${each.key}"
  image_tag_mutability = "MUTABLE" # `latest` tag gets reused on every deploy

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

# Keep the last 30 tagged images per repo. Older builds are still retrievable
# from CI artifacts and ECS task-definition revisions if a rollback older than
# 30 deploys ever becomes necessary — but the working set is much smaller.
resource "aws_ecr_lifecycle_policy" "service" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 30 tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "main", "latest"]
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
    ]
  })
}
