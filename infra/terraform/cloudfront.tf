resource "aws_cloudfront_origin_access_control" "files" {
  name                              = "aec-${var.environment}-files-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "files" {
  enabled             = true
  default_root_object = ""
  price_class         = "PriceClass_200"

  origin {
    domain_name              = aws_s3_bucket.files.bucket_regional_domain_name
    origin_id                = "s3-files"
    origin_access_control_id = aws_cloudfront_origin_access_control.files.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-files"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
}

data "aws_iam_policy_document" "cloudfront_s3" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.files.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.files.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "files" {
  bucket = aws_s3_bucket.files.id
  policy = data.aws_iam_policy_document.cloudfront_s3.json
}
