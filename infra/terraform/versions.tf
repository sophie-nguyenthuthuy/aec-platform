terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.43"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "s3" {
    bucket         = "aec-platform-tfstate"
    key            = "root.tfstate"
    region         = "ap-southeast-1"
    dynamodb_table = "aec-platform-tflock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "aec-platform"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
