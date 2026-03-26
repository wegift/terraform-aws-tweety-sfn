import boto3
from shared.slack import safe_slack_message
from shared.rollout import update_stepfunc_weight

stepfunctions = boto3.client("stepfunctions")
sts = boto3.client("sts")


def handler(event, context):
    """Main handler to start gradual rollout and update Step Function weights."""
    try:
        validation_result = validate_event(event)
        if validation_result:
            return validation_result

        if event.get("custom_weights") is not None:
            weights = generate_custom_weights(event["custom_weights"])
        else:
            weights = generate_weights(event["steps"])

        alias_arn = event["alias_arn"]
        stable_version_arn = get_stepfunc_current_alias_version(alias_arn)

        new_version_arn = event["new_version_arn"]
        sfn_arn, name, new_version = extract_step_function_details(new_version_arn)
        next_weight = weights[0]

        config = build_config(
            event,
            alias_arn,
            name,
            new_version,
            stable_version_arn,
            next_weight,
        )

        slack_message = {
            "title": f"Gradual rollout started for `{name}` step function",
            "status": "started"
        }
        thread_id = safe_slack_message(
            event["notification_slack_channel"],
            config,
            slack_message,
        ).get("ts")

        update_stepfunc_weight(
            alias_arn,
            stable_version_arn,
            new_version_arn,
            next_weight,
        )

        return {
            "status": "success",
            **config,
            "stable_version_arn": stable_version_arn,
            "unqualified_arn": sfn_arn,
            "weights": weights,
            "slack_thread_id": thread_id,
            "next_weight": next_weight,
            "weight_idx": 0,
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
        "new_version_arn",
        "interval",
        "notification_slack_channel",
        "context",
    ]
    missing_fields = [field for field in required_fields if field not in event]
    if missing_fields:
        return error_response(
            "InvalidInput",
            f"Missing required field(s): {', '.join(missing_fields)}",
        )

    if not isinstance(event["context"], dict):
        return error_response("InvalidInput", "'context' must be a dictionary")

    if "execution_arn" not in event["context"]:
        return error_response(
            "InvalidInput",
            "Missing required field: context.execution_arn",
        )

    custom_weights = event.get("custom_weights")
    steps = event.get("steps")

    if custom_weights is None and steps is None:
        return error_response(
            "InvalidInput",
            "Either 'custom_weights' or 'steps' must be provided",
        )

    if custom_weights is not None and steps is not None:
        return error_response(
            "InvalidInput",
            "Provide only one of 'custom_weights' or 'steps', not both",
        )

    if custom_weights is not None:
        if not isinstance(custom_weights, list):
            return error_response(
                "InvalidInput",
                "'custom_weights' must be a list",
            )

        if not custom_weights:
            return error_response(
                "InvalidInput",
                "'custom_weights' must be a non-empty list",
            )

        invalid_weights = [
            weight for weight in custom_weights
            if not isinstance(weight, int) or weight <= 0
        ]
        if invalid_weights:
            return error_response(
                "InvalidInput",
                "'custom_weights' must contain only positive integers",
            )

    if steps is not None:
        if not isinstance(steps, int) or steps <= 0:
            return error_response(
                "InvalidInput",
                "'steps' must be a positive integer",
            )

    return None


def error_response(error_type, message):
    """Standard error payload returned to Step Functions."""
    return {
        "status": "error",
        "error_type": error_type,
        "message": message,
    }


def generate_custom_weights(custom_weights):
    """Generate weights starting with custom weights and continue increasing by the last step until 100 is reached."""
    weights = []
    next_weight = 0

    for custom_step in custom_weights:
        next_weight += custom_step
        weights.append(min(next_weight, 100))
        if next_weight >= 100:
            return weights

    last_step = custom_weights[-1]
    while next_weight < 100:
        next_weight += last_step
        weights.append(min(next_weight, 100))

    return weights


def generate_weights(steps):
    """Generate a list of rounded weights based on the number of steps."""
    delta = 100 / steps
    return [round((i + 1) * delta) for i in range(steps)]


def get_stepfunc_current_alias_version(alias_arn):
    """Fetch the current stable version ARN for the given alias ARN."""
    try:
        res = stepfunctions.describe_state_machine_alias(
            stateMachineAliasArn=alias_arn
        )
        if len(res.get("routingConfiguration", [])) != 1:
            raise Exception(f"Alias {alias_arn} has no single stable version")
        return res.get("routingConfiguration", [{}])[0].get(
            "stateMachineVersionArn", ""
        )
    except Exception as e:
        print(f"Error retrieving alias version: {e}")
        raise


def extract_step_function_details(new_version_arn):
    """Extract the unqualified ARN, name, and version from the new version ARN."""
    arn_segments = new_version_arn.split(":")
    new_version = arn_segments[-1]
    name = arn_segments[-2]
    sfn_arn = new_version_arn.rsplit(":", 1)[0]
    return sfn_arn, name, new_version


def build_config(event, alias_arn, name, new_version, stable_version_arn, next_weight):
    """Build configuration for the rollout based on the event data."""
    return {
        "alias_arn": alias_arn,
        "alias_name": alias_arn.split(":")[-1],
        "environment": get_environment(event),
        "execution_arn": event["context"]["execution_arn"],
        "interval": event["interval"],
        "name": name,
        "new_version": new_version,
        "stable_version": stable_version_arn.split(":")[-1],
        "current_weight": next_weight,
    }


def get_environment(event):
    """Create an identifier for the environment where the gradual rollout is running."""
    environment = event.get("environment")
    if not environment:
        environment = sts.get_caller_identity().get("Account", "Unknown")
    return environment
