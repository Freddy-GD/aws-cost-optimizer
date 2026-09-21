terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.9"
    }
  }
}


resource "aws_sns_topic" "cost_alerts" {
  name = var.topic_name
  tags = {
    "cost-center" = "personal-learning"
  }
}

resource "aws_sns_topic_subscription" "email_alerts" {
  topic_arn = aws_sns_topic.cost_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "cost-alerter-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "lambda_permissions" {
  statement {
    actions   = ["ec2:DescribeInstances", "ec2:DescribeVolumes", "ec2:DescribeAddresses", "pricing:GetProducts"]
    resources = ["*"]
  }
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.cost_alerts.arn]
  }
}

resource "aws_iam_role_policy" "lambda_permissions" {
  name   = "cost-alerter-lambda-permissions"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_permissions.json
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda_function.py"
  output_path = "${path.module}/lambda_function.zip"
}

resource "aws_lambda_function" "cost_alerter" {
  function_name    = "cost-alerter"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256


  environment {
    variables = {
      SNS_TOPIC_ARN = aws_sns_topic.cost_alerts.arn
    }
  }
}

resource "aws_cloudwatch_event_rule" "daily_check" {
  name                = "cost-alerter-daily"
  schedule_expression = "rate(1 day)"
}

resource "time_sleep" "wait_for_event" {
  depends_on      = [aws_cloudwatch_event_rule.daily_check]
  create_duration = "30s"
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule       = aws_cloudwatch_event_rule.daily_check.name
  arn        = aws_lambda_function.cost_alerter.arn
  depends_on = [time_sleep.wait_for_event]
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  principal     = "events.amazonaws.com"
  function_name = aws_lambda_function.cost_alerter.function_name
  source_arn    = aws_cloudwatch_event_rule.daily_check.arn
}

output "topic_arn" {
  value = aws_sns_topic.cost_alerts.arn
}
