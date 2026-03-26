terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "> 5.63"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = "> 1.10"
    }
  }
}