terraform {
  required_version = "~> 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.11"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = "~> 1.10"
    }
  }
}
