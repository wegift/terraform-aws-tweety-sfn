import boto3

stepfunctions = boto3.client("stepfunctions")


def update_stepfunc_weight(alias_arn, stable_version_arn, new_version_arn, next_weight):
    """Update the weight configuration of a Step Functions alias."""
    routing_config = [
        {
            "stateMachineVersionArn": new_version_arn,
            "weight": next_weight,
        }
    ]

    if next_weight < 100:
        routing_config.append(
            {
                "stateMachineVersionArn": stable_version_arn,
                "weight": 100 - next_weight,
            }
        )

    try:
        stepfunctions.update_state_machine_alias(
            stateMachineAliasArn=alias_arn,
            routingConfiguration=routing_config,
        )
    except Exception as e:
        print(f"Error updating Step Functions alias: {e}")
        raise


def get_current_weight(alias_arn):
    """Get the current weight of a specific Step Functions version in the alias."""
    try:
        res = stepfunctions.describe_state_machine_alias(
            stateMachineAliasArn=alias_arn
        )
        return res.get("routingConfiguration", [{}])[0].get("weight", 0)

    except Exception as e:
        print(f"Error retrieving current weight: {e}")
        return None
