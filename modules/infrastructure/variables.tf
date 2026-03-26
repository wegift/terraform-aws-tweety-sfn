variable "name_prefix" {
  type        = string
  description = "Prefix for the Tweety infrastructure, if multiple instances are created"
  default     = ""
}

variable "slack_token_ssm_parameter" {
  type        = string
  description = "SSM parameter name containing the Slack token used for rollout notifications."
}
