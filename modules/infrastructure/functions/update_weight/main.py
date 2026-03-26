import boto3
from shared.slack import safe_slack_message
from shared.rollout import get_current_weight, update_stepfunc_weight

client = boto3.client("stepfunctions")


def handler(event, context):
    """Main handler for managing step function rollout."""
    try:
        validation_result = validate_event(event)
        if validation_result:
            return validation_result

        config = event["config"]
        weights = config["weights"]
        new_version_arn = event["new_version_arn"]
        alias_arn = event["alias_arn"]
        stable_version_arn = config["stable_version_arn"]
        weight_idx = config["weight_idx"]

        next_weight = get_next_weight(weights, weight_idx)
        if isinstance(next_weight, dict) and next_weight.get("status") == "error":
            return next_weight

        current_weight = get_current_weight(alias_arn)

        # If already at 100%, assume rollout is complete or rollback already happened.
        if current_weight == 100:
            return {
                "status": "success",
                "result": "NO_OP",
                "message": "Current weight is already 100%",
                **config,
                "weight_idx": weight_idx,
                "next_weight": current_weight,
            }

        update_stepfunc_weight(
            alias_arn,
            stable_version_arn,
            new_version_arn,
            next_weight,
        )

        status = "success" if next_weight == 100 else "running"
        title = (
            f"Gradual rollout {'succeeded' if status == 'success' else 'in progress'} "
            f"for `{config['name']}` step function"
        )

        send_rollout_update(
            event["notification_slack_channel"],
            config,
            title,
            "running",
            next_weight
        )

        if next_weight == 100:
            send_rollout_update(
                event["notification_slack_channel"],
                config,
                title,
                status,
                next_weight
            )

        return {
            "status": "success",
            "result": "COMPLETED" if next_weight == 100 else "UPDATED",
            **config,
            "weight_idx": weight_idx + 1,
            "next_weight": next_weight,
        }

    except Exception as e:
        print(f"Unexpected error: {e}")
        return error_response("HandlerFailure", str(e))


def validate_event(event):
    """Validate all required event input."""
    if not isinstance(event, dict):
        return error_response("InvalidInput", "Event must be a dictionary")

    required_fields = [
        "alias_arn",
        "new_version_arn",
        "notification_slack_channel",
        "config",
    ]
    missing_fields = [field for field in required_fields if field not in event]
    if missing_fields:
        return error_response(
            "InvalidInput",
            f"Missing required field(s): {', '.join(missing_fields)}",
        )

    config = event["config"]
    if not isinstance(config, dict):
        return error_response("InvalidInput", "'config' must be a dictionary")

    required_config_fields = [
        "weights",
        "weight_idx",
        "stable_version_arn",
        "name",
    ]
    missing_config_fields = [
        field for field in required_config_fields if field not in config
    ]
    if missing_config_fields:
        return error_response(
            "InvalidInput",
            f"Missing required config field(s): {', '.join(missing_config_fields)}",
        )

    weights = config["weights"]
    if not isinstance(weights, list) or not weights:
        return error_response(
            "InvalidInput",
            "'config.weights' must be a non-empty list",
        )

    invalid_weights = [
        weight
        for weight in weights
        if not isinstance(weight, int) or weight <= 0 or weight > 100
    ]
    if invalid_weights:
        return error_response(
            "InvalidInput",
            "'config.weights' must contain only integers between 1 and 100",
        )

    if sorted(weights) != weights:
        return error_response(
            "InvalidInput",
            "'config.weights' must be in ascending order",
        )

    weight_idx = config["weight_idx"]
    if not isinstance(weight_idx, int) or weight_idx < 0:
        return error_response(
            "InvalidInput",
            "'config.weight_idx' must be a non-negative integer",
        )

    if weight_idx >= len(weights):
        return error_response(
            "InvalidInput",
            "'config.weight_idx' is out of range for 'config.weights'",
        )

    if weight_idx + 1 >= len(weights):
        return error_response(
            "InvalidInput",
            "No next weight available in rollout progression",
        )

    return None


def error_response(error_type, message):
    """Standard error payload returned to Step Functions."""
    return {
        "status": "error",
        "error_type": error_type,
        "message": message,
    }


def get_next_weight(weights, weight_idx):
    """Get the next weight in the rollout sequence."""
    try:
        return weights[weight_idx + 1]
    except (TypeError, IndexError) as e:
        return error_response("InvalidInput", f"Invalid weight progression: {e}")


def send_rollout_update(channel, config, title, status, current_weight):
    """Send Slack message updates during the rollout process."""
    try:
        message = {
            "title": title,
            "status": status
        }
        if status == "running":
            message["current_weight"] = current_weight

        safe_slack_message(channel, config, message)

    except Exception as e:
        print(f"Failed to send Slack message: {e}")