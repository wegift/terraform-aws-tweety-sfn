locals {
  non_gradual_routing = [{
    stateMachineVersionArn = var.version_arn,
    weight                 = 100
  }]
}

resource "null_resource" "update_alias_version" {
  count = var.trigger_gradual_rollout ? 0 : 1

  triggers = {
    sfn_version = var.version_arn
  }

  provisioner "local-exec" {
    command = <<EOT
      if [ ${var.version_arn} != ${local.current_version_arn} ]; then 
        aws stepfunctions update-state-machine-alias \
          --state-machine-alias-arn $ALIAS_ARN \
          --routing-configuration '${jsonencode(local.non_gradual_routing)}' \
          --region ${data.aws_region.current.name}
      fi
    EOT

    environment = {
      ALIAS_ARN = aws_sfn_alias.gradual_rollout_alias.arn
    }
  }

  depends_on = [aws_sfn_alias.gradual_rollout_alias]
}
