resource "aws_sns_topic" "alerts" {
  count = var.alert_email == "" ? 0 : 1
  name  = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  alarm_actions = var.alert_email == "" ? [] : [aws_sns_topic.alerts[0].arn]
}

# Fires on any failed sync, e.g. expired Garmin tokens (re-run the bootstrap script).
resource "aws_cloudwatch_metric_alarm" "gateway_errors" {
  alarm_name          = "${local.name}-sync-errors"
  alarm_description   = "Garmin sync failed. Check gateway logs; if auth failed, re-run scripts/bootstrap_garmin_auth.py."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.gateway.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# Fires when no successful sync is recorded for 24 h (catches a broken schedule too).
# SyncSuccess is emitted by the gateway via CloudWatch Embedded Metric Format.
resource "aws_cloudwatch_metric_alarm" "stale_data" {
  alarm_name          = "${local.name}-stale-data"
  alarm_description   = "No successful Garmin sync in 24 hours."
  namespace           = "GarminCoach"
  metric_name         = "SyncSuccess"
  statistic           = "Sum"
  period              = 43200
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}
