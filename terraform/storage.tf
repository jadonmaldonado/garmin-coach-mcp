# Single-table design; see app/common/store.py for the key layout.
resource "aws_dynamodb_table" "main" {
  name                        = local.name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "PK"
  range_key                   = "SK"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# Secret path segment for the connector URL.
resource "random_password" "mcp_path_token" {
  length  = 48
  special = false
}

resource "aws_ssm_parameter" "mcp_token" {
  name  = "/${local.name}/mcp-path-token"
  type  = "SecureString"
  value = random_password.mcp_path_token.result
}

# Garmin OAuth tokens. Terraform only creates the placeholder; the bootstrap script
# writes the real value and the gateway Lambda keeps it refreshed.
resource "aws_ssm_parameter" "garmin_tokens" {
  name  = "/${local.name}/garmin-tokens"
  type  = "SecureString"
  tier  = "Intelligent-Tiering"
  value = "PLACEHOLDER_RUN_BOOTSTRAP"

  lifecycle {
    ignore_changes = [value, tier]
  }
}
