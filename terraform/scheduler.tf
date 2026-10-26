data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.gateway.arn
    }]
  })
}

resource "aws_scheduler_schedule" "sync" {
  name                         = "${local.name}-sync"
  description                  = "Pull recent Garmin data into DynamoDB"
  schedule_expression          = var.sync_schedule
  schedule_expression_timezone = var.athlete_timezone

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 10 # jitter so requests don't land on Garmin at :00 sharp
  }

  target {
    arn      = aws_lambda_function.gateway.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ action = "sync", days = var.sync_days })

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}
