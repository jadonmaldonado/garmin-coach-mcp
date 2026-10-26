data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---------- Gateway: the only role that can read/write Garmin tokens ----------

resource "aws_iam_role" "gateway" {
  name               = "${local.name}-gateway"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "gateway" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.gateway.arn}:*"]
  }

  statement {
    sid       = "GarminTokens"
    actions   = ["ssm:GetParameter", "ssm:PutParameter"]
    resources = [aws_ssm_parameter.garmin_tokens.arn]
  }

  statement {
    sid       = "WriteData"
    actions   = ["dynamodb:PutItem", "dynamodb:BatchWriteItem"]
    resources = [aws_dynamodb_table.main.arn]
  }
}

resource "aws_iam_role_policy" "gateway" {
  role   = aws_iam_role.gateway.id
  policy = data.aws_iam_policy_document.gateway.json
}

# ---------- MCP server: read-only data, no Garmin credentials ----------

resource "aws_iam_role" "mcp" {
  name               = "${local.name}-mcp"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "mcp" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.mcp.arn}:*"]
  }

  statement {
    sid       = "PathToken"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.mcp_token.arn]
  }

  statement {
    sid       = "ReadData"
    actions   = ["dynamodb:GetItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.main.arn]
  }

  statement {
    sid       = "InvokeGateway"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.gateway.arn]
  }
}

resource "aws_iam_role_policy" "mcp" {
  role   = aws_iam_role.mcp.id
  policy = data.aws_iam_policy_document.mcp.json
}
