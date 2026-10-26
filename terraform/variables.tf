variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-west-2"
}

variable "project_name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "garmin-coach"
}

variable "athlete_timezone" {
  description = "IANA timezone; defines 'today' and the sync schedule's clock."
  type        = string
  default     = "America/Los_Angeles"
}

variable "athlete_goals" {
  description = "Free-text goals passed to Claude in the server instructions."
  type        = string
  default     = "Marathon build, then IRONMAN California 2027."
}

variable "race_calendar" {
  description = "Target races, e.g. [{ name = \"...\", date = \"YYYY-MM-DD\", priority = \"A\" }]."
  type = list(object({
    name     = string
    date     = string
    priority = optional(string, "A")
  }))
  default = []
}

variable "athlete_max_hr" {
  description = "Max heart rate for the TRIMP fallback. 0 = use the highest max HR seen in your activities."
  type        = number
  default     = 0
}

variable "sync_schedule" {
  description = "EventBridge Scheduler expression (evaluated in athlete_timezone)."
  type        = string
  default     = "cron(0 6,12,18,22 * * ? *)"
}

variable "sync_days" {
  description = "Days re-synced on each scheduled run (Garmin revises recent data, e.g. late sleep scores)."
  type        = number
  default     = 3
}

variable "lambda_architecture" {
  description = "arm64 (Graviton, cheaper per GB-second) or x86_64. Must match scripts/build.sh."
  type        = string
  default     = "arm64"

  validation {
    condition     = contains(["arm64", "x86_64"], var.lambda_architecture)
    error_message = "lambda_architecture must be arm64 or x86_64."
  }
}

variable "gateway_reserved_concurrency" {
  description = "Set to 1 to guarantee no overlapping Garmin syncs. -1 = unreserved (new accounts with a 10-execution quota can't reserve)."
  type        = number
  default     = -1
}

variable "api_rate_limit" {
  description = "Steady-state requests/second allowed on the MCP endpoint (denial-of-wallet guard)."
  type        = number
  default     = 5
}

variable "api_burst_limit" {
  description = "Burst requests allowed on the MCP endpoint."
  type        = number
  default     = 10
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention."
  type        = number
  default     = 14
}

variable "alert_email" {
  description = "Email for sync failure alerts. Empty = alarms without notifications."
  type        = string
  default     = ""
}

variable "deletion_protection" {
  description = "Protect the DynamoDB table from deletion. Turn on once you rely on the history."
  type        = bool
  default     = false
}
