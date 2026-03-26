output "alias_arn" {
  value       = aws_sfn_alias.gradual_rollout_alias.arn
  description = "Alias ARN, which can be used to reference the rollout in the parents."
}
