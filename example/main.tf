resource "aws_iam_role" "sfn_role" {
  name = "step-functions-example-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_sfn_state_machine" "example" {
  name     = "example"
  role_arn = aws_iam_role.sfn_role.arn
  publish  = true

  definition = templatefile("${path.module}/example.asl.json", {})
}

module "simple_rollout" {
  source = "../"

  alias_name  = "simple" # Optional, defaults to live
  version_arn = aws_sfn_state_machine.example.state_machine_version_arn

  trigger_gradual_rollout = true # Defaults to true

  traffic_shift_interval_sec = 60
  traffic_shift_percentage   = 20

  healthcheck_interval_sec = 10  # How often metrics will be checked during gradual rollout
  latency_threshold_ms     = 100 # Max duration of the step function we are rolling out. Used for degradation check

  slack_channel_id = "CHANNEL1234"
}

module "no_gradual_rollout" {
  source = "../"

  alias_name  = "nope"
  version_arn = aws_sfn_state_machine.example.state_machine_version_arn

  trigger_gradual_rollout = false
}

module "custom_steps" {
  source = "../"

  alias_name  = "custom_steps"
  version_arn = aws_sfn_state_machine.example.state_machine_version_arn

  # This will translate to weights [10, 10, 35, 60, 85, 100]
  custom_steps         = [10, 0, 25]
  latency_threshold_ms = 100

  slack_channel_id = "CHANNEL1234"
}

module "create_infrastructure" {
  source = "../"

  alias_name  = "infra"
  version_arn = aws_sfn_state_machine.example.state_machine_version_arn

  create_infrastructure     = true
  slack_token_ssm_parameter = "/slack/token"
  tweety_prefix             = "example"

  trigger_gradual_rollout = true # Defaults to true

  traffic_shift_percentage = 20
  latency_threshold_ms     = 100

  slack_channel_id = "CHANNEL1234"
}

module "custom_monitor" {
  source = "../"

  alias_name  = "custom_monitor"
  version_arn = aws_sfn_state_machine.example.state_machine_version_arn

  traffic_shift_percentage = 20
  latency_threshold_ms     = 100

  additional_alarms = [aws_cloudwatch_metric_alarm.additional_alarm.alarm_name]

  slack_channel_id = "CHANNEL1234"
}

resource "aws_cloudwatch_metric_alarm" "additional_alarm" {
  alarm_name          = "example-api-monitor"
  alarm_description   = "Monitor 5xx errors on the API endpoint"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  period              = 60
  unit                = "Count"
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/ApiGateway"
  metric_name = "5XXError"
  statistic   = "Maximum"

  dimensions = {
    ApiName  = "api-name"
    Resource = "/endpoint-path"
    Method   = "POST"
  }
}
