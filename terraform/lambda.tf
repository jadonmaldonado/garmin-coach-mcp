# Run scripts/build.sh first; it fills ../build/<function>/ with code + dependencies.
data "archive_file" "gateway" {
  type        = "zip"
  source_dir  = "${path.module}/../build/gateway"
  output_path = "${path.module}/../dist/gateway.zip"
}

data "archive_file" "mcp" {
  type        = "zip"
  source_dir  = "${path.module}/../build/mcp_server"
  output_path = "${path.module}/../dist/mcp_server.zip"
}

resource "aws_cloudwatch_log_group" "gateway" {
  name              = "/aws/lambda/${local.name}-gateway"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "mcp" {
  name              = "/aws/lambda/${local.name}-mcp"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "gateway" {
  function_name                  = "${local.name}-gateway"
  description                    = "Syncs Garmin Connect data into DynamoDB; the only component with Garmin access."
  role                           = aws_iam_role.gateway.arn
  runtime                        = "python3.12"
  architectures                  = [var.lambda_architecture]
  handler                        = "gateway_handler.lambda_handler"
  filename                       = data.archive_file.gateway.output_path
  source_code_hash               = data.archive_file.gateway.output_base64sha256
  memory_size                    = 512
  timeout                        = 900
  reserved_concurrent_executions = var.gateway_reserved_concurrency

  environment {
    variables = {
      TABLE_NAME          = aws_dynamodb_table.main.name
      GARMIN_TOKENS_PARAM = aws_ssm_parameter.garmin_tokens.name
      ATHLETE_TIMEZONE    = var.athlete_timezone
      HOME                = "/tmp"
    }
  }

  depends_on = [aws_cloudwatch_log_group.gateway]
}

resource "aws_lambda_function" "mcp" {
  function_name    = "${local.name}-mcp"
  description      = "Stateless MCP server (Streamable HTTP) for Claude custom connectors."
  role             = aws_iam_role.mcp.arn
  runtime          = "python3.12"
  architectures    = [var.lambda_architecture]
  handler          = "mcp_handler.lambda_handler"
  filename         = data.archive_file.mcp.output_path
  source_code_hash = data.archive_file.mcp.output_base64sha256
  memory_size      = 256
  timeout          = 28 # just under API Gateway's 30 s integration limit

  environment {
    variables = {
      TABLE_NAME            = aws_dynamodb_table.main.name
      MCP_TOKEN_PARAM       = aws_ssm_parameter.mcp_token.name
      GATEWAY_FUNCTION_NAME = aws_lambda_function.gateway.function_name
      ATHLETE_TIMEZONE      = var.athlete_timezone
      ATHLETE_GOALS         = var.athlete_goals
      ATHLETE_MAX_HR        = tostring(var.athlete_max_hr)
      RACE_CALENDAR         = jsonencode(var.race_calendar)
    }
  }

  depends_on = [aws_cloudwatch_log_group.mcp]
}
