resource "aws_sfn_alias" "gradual_rollout_alias" {
  name        = var.alias_name
  description = var.alias_description

  routing_configuration {
    state_machine_version_arn = var.version_arn
    weight                    = 100
  }

  lifecycle {
    ignore_changes = [routing_configuration]
  }
}
