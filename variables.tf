variable "additional_alarms" {
  type        = list(string)
  description = "A list of additional CloudWatch alarm names to monitor during the gradual rollout process."
  default     = []
}

variable "alias_description" {
  type        = string
  description = "Custom description of the new alias, created for the gradual rollout."
  default     = "Gradual rollout alias."
}

variable "alias_name" {
  type        = string
  description = "The new alias name which will be created for the gradual rollouts. Defaults to live."
  default     = "live"
}

variable "create_infrastructure" {
  type        = bool
  description = "Whether to create a new tweety-sfn for the gradual rollout. By default, it'll try to reuse the `tweety-sfn`."
  default     = false
}

variable "custom_steps" {
  type        = list(number)
  description = "Instead of linear gradual deployment, it's possible to customise the steps according to rollout requirements. Required if `traffic_shift_percentage` is not set."
  default     = null

  validation {
    condition     = var.trigger_gradual_rollout && var.custom_steps == null ? var.traffic_shift_percentage != null : true
    error_message = "At least one of the following field required: `custom_steps` or traffic_shift_percentage`."
  }

  validation {
    condition     = var.trigger_gradual_rollout && var.custom_steps != null ? var.traffic_shift_percentage == null : true
    error_message = "Only one of the following fields are allowed: `custom_steps` or traffic_shift_percentage`."
  }

  validation {
    condition     = (((length(coalesce(var.custom_steps, []))) * 9) + (((((length(coalesce(var.custom_steps, [])))) * var.traffic_shift_interval_sec) / var.healthcheck_interval_sec) * 9) + 15) < 23500
    error_message = "This configuration may cause Tweety to exceed the 25000 state transition threshold. Please try: increasing the time between health checks, decreasing the interval between traffic shifts, or decreasing the number of traffic shifts. See the documentation for the formula."
  }
}

variable "environment" {
  type        = string
  description = "Application environment name to be used during the notifications. If not configured the account name is used."
  default     = null
}

variable "healthcheck_interval_sec" {
  type        = number
  description = "Frequency of the metric checks during the gradual rollout, defined in seconds."
  default     = 30

  validation {
    condition     = var.healthcheck_interval_sec < var.traffic_shift_interval_sec
    error_message = "`healthcheck_interval_sec` must be more less than `traffic_shift_interval_sec` to ensure health of the gradual rollout."
  }
}

variable "latency_threshold_ms" {
  type        = number
  description = "Maximum duration of the step function can run before rollback is initiated, defined in seconds."
  default     = null

  validation {
    condition     = var.trigger_gradual_rollout ? var.latency_threshold_ms != null : true
    error_message = "Latency threshold required if trigger_gradual_rollout is enabled."
  }
}

variable "slack_token_ssm_parameter" {
  type        = string
  description = "SSM parameter name containing the Slack token used for rollout notifications."
  default     = ""

  validation {
    condition = var.create_infrastructure ? (
      length(trimspace(var.slack_token_ssm_parameter)) > 0 &&
      startswith(var.slack_token_ssm_parameter, "/")
    ) : true
    error_message = "`slack_token_ssm_parameter` is required when `create_infrastructure` is true and should be a valid SSM parameter path starting with '/'."
  }
}

variable "slack_channel_id" {
  type        = string
  description = "Slack channel ID where the rollout notifications will be sent to."
  default     = null

  validation {
    condition     = var.trigger_gradual_rollout ? var.slack_channel_id != null : true
    error_message = "`slack_channel_id` is required when gradual rollout is triggered."
  }
}

variable "traffic_shift_interval_sec" {
  type        = number
  description = "Frequency of the traffic shifting assuming the health checks are passing, defined in seconds."
  default     = 60
}

variable "traffic_shift_percentage" {
  type        = number
  description = "Percentage of the traffic that's being increased in each interval. Required if `custom_steps` is not set."
  default     = null

  validation {
    condition     = var.traffic_shift_percentage != null ? contains([null, 1, 2, 5, 10, 20, 25, 50], var.traffic_shift_percentage) : true
    error_message = "Invalid percentage value. Valid values are: [1, 2, 5, 10, 20, 25, 50]."
  }
  validation {
    condition     = (((100 / coalesce(var.traffic_shift_percentage, 100)) * 9) + ((((100 / coalesce(var.traffic_shift_percentage, 100)) * var.traffic_shift_interval_sec) / var.healthcheck_interval_sec) * 9) + 15) < 23500
    error_message = "This configuration may cause Tweety to exceed the 25000 state transition threshold. Please try: increasing the time between health checks, increasing the traffic shift % per interval, or decreasing the interval between traffic shifts. See the documentation for the formula."
  }
}

variable "trigger_gradual_rollout" {
  type        = bool
  description = "Specifies whether gradual rollout will be triggered."
  default     = true
}

variable "tweety_prefix" {
  type        = string
  description = "Prefix used when creating the Tweety Step Functions infrastructure."
  default     = ""

  validation {
    condition     = var.create_infrastructure ? length(trimspace(var.tweety_prefix)) > 0 : true
    error_message = "`tweety_prefix` is required when `create_infrastructure` is true."
  }
}

variable "version_arn" {
  type        = string
  description = "ARN pointing to the new version of the step function we wish to roll out."
}

variable "override_error_rate_monitor" {
  type        = bool
  description = "If set to true, disables error rate monitoring during health checks. Make sure you have other ways to monitor errors."
  default     = false

  validation {
    condition     = var.override_error_rate_monitor ? length(var.additional_alarms) > 0 : true
    error_message = "When `override_error_rate_monitor` is true, at least one `additional_alarm` must be configured to ensure proper error monitoring."
  }
}
