import os
from datetime import datetime, timedelta

import boto3
from shared.slack import safe_slack_message
from shared.rollout import get_current_weight, update_stepfunc_weight

cloudwatch = boto3.client("cloudwatch")


def handler(event, context):
    """Handler for managing gradual rollout and rollback upon failure."""
    try:
        validation_result = validate_event(event)
        if validation_result:
            return validation_result

        config = event["config"]
        additional_alarms = event.get("additional_alarms", [])
        alias_name = config["alias_name"]
        latency_threshold = event["latency_threshold"]
        sfn_arn = config["unqualified_arn"]
        version = config["new_version"]
        override_error_rate_monitor = event.get("override_error_rate_monitor", False)

        health_check_res = health_check(
            sfn_arn=sfn_arn,
            version=version,
            alias_name=alias_name,
            latency_threshold=latency_threshold,
            override_error_rate_monitor=override_error_rate_monitor,
            additional_alarms=additional_alarms,
        )

        if health_check_res == "SUCCEEDED":
            alias_arn = event["alias_arn"]
            current_weight = get_current_weight(alias_arn)
            return {
                "status": "success",
                "result": "COMPLETED" if current_weight == 100 else "SUCCEEDED",
            }

        handle_rollout_failure(event, health_check_res)
        return {
            "status": "success",
            "result": "FAILED",
            "reason": health_check_res,
        }

    except Exception as e:
        print(f"Error in handler: {e}")
        return error_response("HandlerFailure", str(e))


def validate_event(event):
    """Validate all required event input."""
    if not isinstance(event, dict):
        return error_response("InvalidInput", "Event must be a dictionary")

    required_fields = [
        "alias_arn",
        "config",
        "latency_threshold",
        "notification_slack_channel",
    ]
    missing_fields = [field for field in required_fields if field not in event]
    if missing_fields:
        return error_response(
            "InvalidInput",
            f"Missing required field(s): {', '.join(missing_fields)}",
        )

    if not isinstance(event["config"], dict):
        return error_response("InvalidInput", "'config' must be a dictionary")

    required_config_fields = [
        "alias_name",
        "unqualified_arn",
        "new_version",
        "stable_version_arn",
        "name",
    ]
    missing_config_fields = [
        field for field in required_config_fields if field not in event["config"]
    ]
    if missing_config_fields:
        return error_response(
            "InvalidInput",
            f"Missing required config field(s): {', '.join(missing_config_fields)}",
        )

    latency_threshold = event["latency_threshold"]
    if not isinstance(latency_threshold, (int, float)) or latency_threshold <= 0:
        return error_response(
            "InvalidInput",
            "'latency_threshold' must be a positive number",
        )

    additional_alarms = event.get("additional_alarms", [])
    if not isinstance(additional_alarms, list):
        return error_response(
            "InvalidInput",
            "'additional_alarms' must be a list",
        )

    if any(not isinstance(alarm, str) or not alarm.strip() for alarm in additional_alarms):
        return error_response(
            "InvalidInput",
            "'additional_alarms' must contain only non-empty strings",
        )

    override_error_rate_monitor = event.get("override_error_rate_monitor", False)
    if not isinstance(override_error_rate_monitor, bool):
        return error_response(
            "InvalidInput",
            "'override_error_rate_monitor' must be a boolean",
        )

    return None


def error_response(error_type, message):
    """Standard error payload returned to Step Functions."""
    return {
        "status": "error",
        "error_type": error_type,
        "message": message,
    }


def health_check(
    sfn_arn,
    version,
    alias_name,
    latency_threshold,
    override_error_rate_monitor,
    additional_alarms,
):
    """Check the health of the step function by evaluating latency and error rates."""
    now = datetime.utcnow()
    start_time = now - timedelta(minutes=1)

    res = metric_check(sfn_arn, alias_name, "ExecutionTime", start_time, now)
    if res is None:
        return "failed to retrieve metric `ExecutionTime`"
    if not check_latency(res, latency_threshold):
        return "failed metric check `ExecutionTime`"

    if not override_error_rate_monitor:
        for metric in ["ExecutionsFailed"]:
            res = metric_check(sfn_arn, version, metric, start_time, now)
            if res is None:
                return f"failed to retrieve metric `{metric}`"
            if not check_error_rate(res, metric):
                return f"failed metric check `{metric}`"

    if additional_alarms:
        alarms_in_alert = cloudwatch.describe_alarms(
            AlarmNames=additional_alarms,
            StateValue="ALARM",
        )

        metric_alarm_names = [
            alarm["AlarmName"] for alarm in alarms_in_alert.get("MetricAlarms", [])
        ]
        composite_alarm_names = [
            alarm["AlarmName"] for alarm in alarms_in_alert.get("CompositeAlarms", [])
        ]

        alarm_names = metric_alarm_names + composite_alarm_names
        if alarm_names:
            return f"custom alarm in ALERT state: {', '.join(alarm_names)}"

    return "SUCCEEDED"


def metric_check(sfn_arn, qualifier, metric_name, start_time, end_time):
    """Retrieve metric statistics from CloudWatch for a given state machine version."""
    dimensions = [{"Name": "StateMachineArn", "Value": sfn_arn}]

    try:
        if metric_name == "ExecutionTime":
            dimensions.append({"Name": "Alias", "Value": qualifier})
            response = cloudwatch.get_metric_statistics(
                Namespace="AWS/States",
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                ExtendedStatistics=["p95"],
                Unit="Milliseconds",
            )
        else:
            dimensions.append({"Name": "Version", "Value": qualifier})
            response = cloudwatch.get_metric_statistics(
                Namespace="AWS/States",
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=60,
                Statistics=["Maximum"],
                Unit="Count",
            )

        return response.get("Datapoints", [])

    except Exception as e:
        print(f"Error fetching metrics for {metric_name}: {e}")
        return None


def check_error_rate(datapoints, metric_name):
    """Check if any error datapoint exceeds threshold."""
    for datapoint in datapoints:
        if datapoint.get("Maximum", 0) > 0:
            print(f"Failing health check: {metric_name} error metrics detected")
            return False
    return True


def check_latency(datapoints, latency_threshold):
    """Check if the latency exceeds the given threshold."""
    for datapoint in datapoints:
        p95_latency = datapoint.get("ExtendedStatistics", {}).get("p95", 0)
        if p95_latency > latency_threshold:
            print(
                f"Failing health check: ExecutionTime exceeded "
                f"{latency_threshold}ms with {p95_latency}ms."
            )
            return False
    return True


def handle_rollout_failure(event, health_check_res):
    """Handle the failure case by notifying Slack and initiating rollback."""
    config = event["config"]
    alias_arn = event["alias_arn"]
    stable_version_arn = config["stable_version_arn"]

    for message_type in ["running", "failed"]:
        safe_slack_message(
            event["notification_slack_channel"],
            config,
            {
                "title": (
                    f"Gradual rollout failed for `{config['name']}` step function "
                    f"due to {health_check_res}. Rollback initiated."
                ),
                "status": message_type
            },
        )

    print(f"Rollback initiated to stable version: {stable_version_arn}")
    update_stepfunc_weight(alias_arn, stable_version_arn, stable_version_arn, 100)
