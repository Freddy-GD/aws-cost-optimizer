terraform {
  cloud {
    organization = "Freddy-terraform"
    workspaces {
      name = "cost-alerter"
    }
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

module "cost-alerter" {
  source      = "./modules/cost-alerter"
  topic_name  = var.topic_name
  alert_email = var.alert_email
}
