from __future__ import annotations

import logging
from typing import Any, Mapping

from sqlalchemy.orm import Session

import models
from services.email_service import EmailService


logger = logging.getLogger(__name__)


EVENT_TITLES: dict[str, str] = {
    "audit.completed": "Audit completed",
    "audit.consensus_ready": "Consensus report ready",
    "alert.triggered": "Monitoring alert triggered",
    "alert.visibility_score_drop": "AI visibility alert triggered",
    "alert.aeo_mention_drop": "Off-page mentions alert triggered",
    "audit.schedule_paused": "Scheduled audit paused",
    "competitive.digest": "Competitive digest ready",
    "project.progress_report": "Progress report generated",
}


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


class NotificationRouter:
    def __init__(self, db: Session):
        self.db = db

    def dispatch_event(
        self,
        *,
        workspace_id: int | None,
        event_key: str,
        context: Mapping[str, Any],
        user: models.User | None = None,
        to_email: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, str]:
        results: dict[str, str] = {}

        if to_email:
            try:
                EmailService(self.db).queue_template_email(
                    to_email=to_email,
                    template_key=event_key,
                    context={**dict(context), "workspace_id": workspace_id},
                    user_id=user.id if user else None,
                    workspace_id=workspace_id,
                    correlation_id=correlation_id,
                )
                results["email"] = "queued"
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to queue %s email notification for %s",
                    event_key,
                    to_email,
                    exc_info=exc,
                )
                results["email"] = "error"

        if workspace_id is None:
            return results

        slack_connection = (
            self.db.query(models.SlackConnection)
            .filter(models.SlackConnection.workspace_id == workspace_id)
            .first()
        )
        if slack_connection is not None:
            try:
                self.send_slack_message(
                    connection=slack_connection,
                    event_key=event_key,
                    context=context,
                )
                results["slack"] = "sent"
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to post %s notification to Slack for workspace %s",
                    event_key,
                    workspace_id,
                    exc_info=exc,
                )
                results["slack"] = "error"

        teams_connection = (
            self.db.query(models.TeamsConnection)
            .filter(models.TeamsConnection.workspace_id == workspace_id)
            .first()
        )
        if teams_connection is not None:
            try:
                self.send_teams_message(
                    connection=teams_connection,
                    event_key=event_key,
                    context=context,
                )
                results["teams"] = "sent"
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to post %s notification to Teams for workspace %s",
                    event_key,
                    workspace_id,
                    exc_info=exc,
                )
                results["teams"] = "error"

        return results

    def send_slack_message(
        self,
        *,
        connection: models.SlackConnection,
        event_key: str,
        context: Mapping[str, Any],
        channel_id: str | None = None,
    ) -> None:
        payload = self.build_slack_payload(
            event_key=event_key,
            context=context,
            channel_id=channel_id or connection.default_channel_id,
        )

        if payload.get("channel") and connection.access_token:
            response = self._post_json(
                "https://slack.com/api/chat.postMessage",
                payload,
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
            if response.get("ok") is not True:
                raise RuntimeError(response.get("error") or "Slack chat.postMessage failed.")
            return

        webhook_url = _string_value(connection.incoming_webhook_url)
        if webhook_url:
            self._post_json(webhook_url, payload, headers=None)
            return

        raise RuntimeError(
            "Slack connection is missing both a default channel and incoming webhook."
        )

    def send_teams_message(
        self,
        *,
        connection: models.TeamsConnection,
        event_key: str,
        context: Mapping[str, Any],
        webhook_url: str | None = None,
    ) -> None:
        target_url = _string_value(webhook_url) or _string_value(connection.webhook_url)
        if not target_url:
            raise RuntimeError("Teams webhook URL is not configured.")
        payload = self.build_teams_payload(event_key=event_key, context=context)
        self._post_json(target_url, payload, headers=None)

    def build_slack_payload(
        self,
        *,
        event_key: str,
        context: Mapping[str, Any],
        channel_id: str | None = None,
    ) -> dict[str, Any]:
        title = EVENT_TITLES.get(event_key, event_key.replace(".", " ").title())
        lines = self._message_lines(context)
        text = " | ".join(lines[:3]) if lines else title
        payload: dict[str, Any] = {
            "text": f"{title}: {text}" if text else title,
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": title[:150]},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join(f"• {line}" for line in lines[:8])
                        or "No additional context.",
                    },
                },
            ],
        }
        if channel_id:
            payload["channel"] = channel_id
        return payload

    def build_teams_payload(self, *, event_key: str, context: Mapping[str, Any]) -> dict[str, Any]:
        title = EVENT_TITLES.get(event_key, event_key.replace(".", " ").title())
        lines = self._message_lines(context)
        facts = [{"title": f"{index + 1}.", "value": line} for index, line in enumerate(lines[:8])]
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "weight": "Bolder",
                                "size": "Medium",
                                "text": title,
                            },
                            {
                                "type": "FactSet",
                                "facts": facts
                                or [{"title": "Info", "value": "No additional context."}],
                            },
                        ],
                    },
                }
            ],
        }

    def _message_lines(self, context: Mapping[str, Any]) -> list[str]:
        ordered_keys = (
            "workspace_name",
            "project_name",
            "target_url",
            "report_url",
            "dashboard_url",
            "settings_url",
            "metric_name",
            "metric_value",
            "condition",
            "threshold",
            "geo_score",
            "seo_score",
            "aeo_score",
            "message",
            "credit_balance",
            "consumed_scans",
            "monthly_limit_scans",
            "consumed_credits",
            "monthly_limit_credits",
        )

        lines: list[str] = []
        for key in ordered_keys:
            value = context.get(key)
            normalized = _string_value(value)
            if normalized:
                label = key.replace("_", " ").capitalize()
                lines.append(f"{label}: {normalized}")

        for key, value in context.items():
            if key in ordered_keys:
                continue
            normalized = _string_value(value)
            if normalized:
                lines.append(f"{key.replace('_', ' ').capitalize()}: {normalized}")

        return lines

    def _post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        from services.url_validation import safe_sync_fetch

        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        response = safe_sync_fetch(
            url,
            method="POST",
            json=dict(payload),
            headers=request_headers,
            timeout=10.0,
        )
        response.raise_for_status()
        if not response.content:
            return {"ok": True}
        try:
            return response.json()
        except ValueError:
            return {"ok": True, "raw": response.text}
