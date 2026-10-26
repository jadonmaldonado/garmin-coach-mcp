output "mcp_connector_url" {
  description = "Paste into Claude > Settings > Connectors > Add custom connector. Treat it like a password."
  value       = "${aws_apigatewayv2_api.mcp.api_endpoint}/mcp/${random_password.mcp_path_token.result}"
  sensitive   = true
}

output "gateway_function_name" {
  value = aws_lambda_function.gateway.function_name
}

output "garmin_tokens_parameter" {
  value = aws_ssm_parameter.garmin_tokens.name
}

output "table_name" {
  value = aws_dynamodb_table.main.name
}

output "aws_region" {
  value = var.aws_region
}
