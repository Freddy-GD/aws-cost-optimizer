terraform {
  cloud {
    organization = "Freddy-terraform"
    workspaces {
      name = "cost-alerter"
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
