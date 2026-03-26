data "aws_caller_identity" "current" {}

data "aws_sfn_state_machine" "gradual_rollout_sfn" {
  count = var.create_infrastructure ? 0 : 1

  name = "tweety-sfn"
}

data "aws_sfn_alias" "live" {
  count = var.create_infrastructure ? 0 : 1

  name             = "live"
  statemachine_arn = data.aws_sfn_state_machine.gradual_rollout_sfn[0].arn
}

module "tweety_infrastructure" {
  count = var.create_infrastructure ? 1 : 0

  source = "./modules/infrastructure"

  name_prefix               = var.tweety_prefix
  slack_token_ssm_parameter = var.slack_token_ssm_parameter
}
