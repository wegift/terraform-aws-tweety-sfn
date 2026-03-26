locals {
  alias_id            = aws_sfn_alias.gradual_rollout_alias.id
  current_version_arn = tolist(data.awscc_stepfunctions_state_machine_alias.gradual_rollout_alias.routing_configuration)[0].state_machine_version_arn

  rollout_payload = merge({
    additional_alarms           = var.additional_alarms
    alias_arn                   = aws_sfn_alias.gradual_rollout_alias.arn,
    environment                 = var.environment,
    healthcheck_interval        = var.healthcheck_interval_sec,
    interval                    = var.traffic_shift_interval_sec,
    latency_threshold           = var.latency_threshold_ms,
    new_version_arn             = var.version_arn,
    notification_slack_channel  = var.slack_channel_id,
    override_error_rate_monitor = var.override_error_rate_monitor
    },
    var.custom_steps != null ?
    { custom_weights = var.custom_steps, steps = null } :
    { custom_weights = null, steps = 100 / coalesce(var.traffic_shift_percentage, 100) }
  )
}

data "aws_region" "current" {}

# We are using the AWSCC for checking as this helps us use the checkes BEFORE terraform runs
data "awscc_stepfunctions_state_machine_alias" "gradual_rollout_alias" {
  id = local.alias_id
}

check "gradual_rollout_deployment_check" {
  assert {
    condition     = length(data.awscc_stepfunctions_state_machine_alias.gradual_rollout_alias.routing_configuration) == 1
    error_message = "CAUTION! Gradual deployment is in progress for ${aws_sfn_alias.gradual_rollout_alias.arn}. If you try to update the SFN during this time your deployment will fail."
  }
}

resource "null_resource" "run_gradual_rollout" {
  count = var.trigger_gradual_rollout ? 1 : 0

  triggers = {
    sfn_version = var.version_arn
  }

  provisioner "local-exec" {
    command = <<EOT
      rollout_in_progress=$(aws stepfunctions describe-state-machine-alias --region ${data.aws_region.current.name} --state-machine-alias-arn $STEP_FUNCTION_ALIAS_ARN --query 'length(routingConfiguration) != `1`')
      if $rollout_in_progress; then
        # Alias traffic routing is not 100% to the given version
        echo "Can't initiate gradual rollout. Deployment in progress"
        exit 1
      fi
    EOT

    environment = {
      STEP_FUNCTION_ALIAS_ARN = aws_sfn_alias.gradual_rollout_alias.arn
    }
  }

  provisioner "local-exec" {
    # Only trigger deployent if the state machine version is not equal to 1
    command = <<EOT
      if [ ${var.version_arn} != ${local.current_version_arn} ]; then 
        aws stepfunctions start-execution \
          --state-machine-arn $GRADUAL_ROLLOUT_SFN \
          --input '${jsonencode(local.rollout_payload)}' \
          --region ${data.aws_region.current.name}
      fi
    EOT

    environment = {
      GRADUAL_ROLLOUT_SFN = var.create_infrastructure ? module.tweety_infrastructure[0].arn : data.aws_sfn_alias.live[0].arn
    }
  }

  depends_on = [aws_sfn_alias.gradual_rollout_alias]
}
