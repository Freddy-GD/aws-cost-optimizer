variable "region" {
  description = "The AWS region to deploy resources in"
  type        = string
  default     = "us-east-1"
}

variable "topic_name" {
  description = "The name of the SNS topic"
  type        = string
  default     = "cost-alerter-topic"
  validation {
    condition     = startswith(var.topic_name, "cost-")
    error_message = "The topic name must start with 'cost-'"
  }
}


variable "alert_email" {
  description = "Email address to receive cost alerts"
  type        = string
}
