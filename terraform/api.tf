resource "aws_apigatewayv2_api" "mcp" {
  name          = "${local.name}-mcp"
  protocol_type = "HTTP"
  description   = "Public MCP endpoint for Claude custom connectors"
}

resource "aws_apigatewayv2_integration" "mcp" {
  api_id                 = aws_apigatewayv2_api.mcp.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.mcp.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_route" "mcp" {
  api_id    = aws_apigatewayv2_api.mcp.id
  route_key = "ANY /mcp/{token}"
  target    = "integrations/${aws_apigatewayv2_integration.mcp.id}"
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${local.name}-mcp"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.mcp.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.api_rate_limit
    throttling_burst_limit = var.api_burst_limit
  }

  # routeKey logs the template ("ANY /mcp/{token}"), never the secret path itself.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId = "$context.requestId"
      time      = "$context.requestTime"
      ip        = "$context.identity.sourceIp"
      routeKey  = "$context.routeKey"
      status    = "$context.status"
      latencyMs = "$context.integrationLatency"
      error     = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.mcp.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.mcp.execution_arn}/*/*"
}
