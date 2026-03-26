import json
import os

import boto3
import urllib3

http = urllib3.PoolManager()
ssm_client = boto3.client("ssm")

SLACK_CREATE_URL = "https://slack.com/api/chat.postMessage"
SLACK_UPDATE_URL = "https://slack.com/api/chat.update"

_slack_token = None

def safe_slack_message(channel_id, config, message):
    try:
        return _send_slack_message(channel_id, config, message)
    except Exception as e:
        print(f"Slack notification failed: {e}")
        return None


def _get_slack_token():
    global _slack_token
    if _slack_token:
        return _slack_token

    _slack_token = ssm_client.get_parameter(
        Name=os.environ["SLACK_TOKEN_SSM_PARAMETER"],
        WithDecryption=True,
    )["Parameter"]["Value"]
    return _slack_token


def _send_slack_message(channel_id, config, message):
    """Send a message to Slack, either creating a new message or updating an existing one."""
    slack_url = _get_slack_url(message["status"])
    headers = {
        "Authorization": f"Bearer {_get_slack_token()}",
        "Content-Type": "application/json",
    }
    body = _format_message(channel_id, message, config)

    try:
        response = http.request("POST", slack_url, headers=headers, body=body)
        payload = json.loads(response.data.decode("utf-8"))

        if response.status != 200:
            print(f"Slack HTTP error {response.status}: {payload}")
            return None

        if not payload.get("ok", False):
            print(f"Slack API error: {payload}")
            return None

        return payload

    except Exception as e:
        print(f"Error sending Slack message: {e}")
        return None


def _get_slack_url(status):
    """Return the appropriate Slack API URL based on the message status."""
    return SLACK_UPDATE_URL if status in ["failed", "success"] else SLACK_CREATE_URL


def _get_status_color(status):
    """Return the color code based on the rollout status."""
    status_colors = {
        "started": "D08F2C",
        "running": "D08F2C",
        "success": "2AAD74",
        "failed": "900003",
    }
    return status_colors.get(status, "900003")


def _format_message(channel_id, message, config):
    """Format the message payload to be sent to Slack."""
    status = message["status"]
    is_running = status == "running"
    is_update = status in ["success", "failed"]

    base_attachments = [
        {
            "mrkdwn_in": ["text"],
            "color": _get_status_color(status),
            "title": message["title"],
            "title_link": _build_execution_link(config["execution_arn"]),
            "fields": _format_message_fields(config, message),
        }
    ]

    running_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"Rollout progress is {message.get('current_weight', 0)}% :milo:",
            },
        }
    ]

    thread_ref = (
        {"ts": config.get("slack_thread_id")}
        if is_update
        else {"thread_ts": config.get("slack_thread_id")}
        if config.get("slack_thread_id")
        else {}
    )

    payload = {
        **thread_ref,
        "channel": channel_id,
        "text": message["title"],
        "username": "Gradual Rollout",
        "icon_url": "https://facts.net/wp-content/uploads/2023/09/21-facts-about-tweety-bird-looney-tunes-1694055420.jpg",
        "attachments": [] if is_running else base_attachments,
        "blocks": running_blocks if is_running else [],
    }

    return json.dumps(payload).encode("utf-8")


def _build_execution_link(execution_arn):
    arn_parts = execution_arn.split(":")
    region = arn_parts[3] if len(arn_parts) > 3 else "us-east-1"
    return f"https://{region}.console.aws.amazon.com/states/home?region={region}#/v2/executions/details/{execution_arn}"


def _format_message_fields(config, message):
    """Helper function to format message fields for the Slack message."""
    fields = []

    environment = config.get("environment")
    if environment:
        fields.append(
            {"title": "Environment", "value": f"`{environment}`", "short": True}
        )

    fields.extend(
        [
            {"title": "Alias", "value": f"`{config['alias_name']}`", "short": True},
            {"title": "Interval", "value": f"{config['interval']} sec", "short": True},
            {
                "title": "Weight",
                "value": f"{message.get('current_weight', config.get('current_weight', 0))}%",
                "short": True,
            },
            {"title": "Stable version", "value": config["stable_version"], "short": True},
            {"title": "New version", "value": config["new_version"], "short": True},
        ]
    )

    return fields
