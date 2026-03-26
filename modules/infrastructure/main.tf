locals {
  tweety_sfn_name = "${var.name_prefix}-tweety-sfn"

  tweety_sfn_lambda_functions = {
    configure_rollout = {
      name = "configure-rollout"
      allowed_actions = [
        "states:DescribeStateMachineAlias",
        "states:UpdateStateMachineAlias"
      ]
    }
    health_check = {
      name = "health-check"
      allowed_actions = [
        "cloudwatch:DescribeAlarms",
        "cloudwatch:GetMetricStatistics",
        "states:DescribeStateMachineAlias",
        "states:UpdateStateMachineAlias"
      ]
    }
    update_weight = {
      name = "update-weight"
      allowed_actions = [
        "states:DescribeStateMachineAlias",
        "states:UpdateStateMachineAlias"
      ]
    }
  }

  tweety_sfn_iam_permissions = {
    lambda = {
      Effect = "Allow"
      Action = ["lambda:InvokeFunction"]
      Resource = [
        "${module.tweety_sfn_lambda["configure_rollout"].lambda_function_arn}:live",
        "${module.tweety_sfn_lambda["health_check"].lambda_function_arn}:live",
        "${module.tweety_sfn_lambda["update_weight"].lambda_function_arn}:live"
      ]
    }
    cloudwatch = {
      Effect = "Allow"
      Action = [
        "logs:UpdateLogDelivery",
        "logs:PutResourcePolicy",
        "logs:ListLogDeliveries",
        "logs:GetLogDelivery",
        "logs:Describe*",
        "logs:CreateLogDelivery"
      ]
      Resource = ["*"]
    }
  }
}

data "aws_ssm_parameter" "slack_token" {
  name = var.slack_token_ssm_parameter
}

resource "aws_iam_role" "tweety_sfn_lambda" {
  for_each = local.tweety_sfn_lambda_functions

  name = "${local.tweety_sfn_name}-${each.value.name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  managed_policy_arns = ["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"]

  dynamic "inline_policy" {
    for_each = can(each.value.allowed_actions) ? [1] : []

    content {
      name = each.key
      policy = jsonencode({
        Version = "2012-10-17"
        Statement = [
          {
            Effect   = "Allow"
            Action   = each.value.allowed_actions
            Resource = "*"
          },
          {
            Effect   = "Allow"
            Action   = "ssm:GetParameter"
            Resource = data.aws_ssm_parameter.slack_token.arn
          }
        ]
      })
    }
  }
}


module "tweety_sfn_lambda" {
  for_each = local.tweety_sfn_lambda_functions

  source  = "terraform-aws-modules/lambda/aws"
  version = "7.7.1"

  source_path = [
    "${path.module}/functions/${each.key}",
    {
      path          = "${path.module}/shared"
      prefix_in_zip = "shared"
    }
  ]

  function_name = "${local.tweety_sfn_name}-${each.value.name}"

  create_role = false
  lambda_role = aws_iam_role.tweety_sfn_lambda[each.key].arn

  runtime = "python3.12"
  handler = "main.handler"
  publish = true

  logging_log_format       = "JSON"
  logging_system_log_level = "WARN"

  cloudwatch_logs_retention_in_days = 30
  timeout                           = 60
  trigger_on_package_timestamp      = false

  environment_variables = {
    SLACK_TOKEN_SSM_PARAMETER = data.aws_ssm_parameter.slack_token.name
  }
}

resource "aws_lambda_alias" "live" {
  for_each = local.tweety_sfn_lambda_functions

  name             = "live"
  function_name    = module.tweety_sfn_lambda[each.key].lambda_function_name
  function_version = module.tweety_sfn_lambda[each.key].lambda_function_version
}

###############################
# Orchastrating step function #
###############################
resource "aws_iam_role" "tweety_sfn" {
  name = local.tweety_sfn_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
      }
    ]
  })

  dynamic "inline_policy" {
    for_each = local.tweety_sfn_iam_permissions

    content {
      name = inline_policy.key
      policy = jsonencode({
        Version   = "2012-10-17"
        Statement = [inline_policy.value]
      })
    }
  }

  depends_on = [module.tweety_sfn_lambda]
}

resource "aws_cloudwatch_log_group" "tweety_sfn_logs" {
  name = "/aws/vendedlogs/states/${local.tweety_sfn_name}"
}

resource "aws_sfn_state_machine" "tweety_sfn" {
  name     = local.tweety_sfn_name
  role_arn = aws_iam_role.tweety_sfn.arn
  publish  = true

  logging_configuration {
    level                  = "ALL"
    include_execution_data = false
    log_destination        = "${aws_cloudwatch_log_group.tweety_sfn_logs.arn}:*"
  }

  definition = templatefile("${path.module}/stepfunction.asl.json", {
    configure_rollout_arn = aws_lambda_alias.live["configure_rollout"].arn,
    health_check_arn      = aws_lambda_alias.live["health_check"].arn,
    update_weight_arn     = aws_lambda_alias.live["update_weight"].arn
  })
}

resource "aws_sfn_alias" "tweety_sfn" {
  name = "live"

  routing_configuration {
    state_machine_version_arn = aws_sfn_state_machine.tweety_sfn.state_machine_version_arn
    weight                    = 100
  }
}
