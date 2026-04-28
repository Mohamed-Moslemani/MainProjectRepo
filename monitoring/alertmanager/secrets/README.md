# Alertmanager receiver secrets

Drop one file per receiver here, with the secret value as the file
contents (no trailing newline, no quoting). The Alertmanager config
references them via `*_file` directives so the values never appear
in `git log` or `docker inspect`.

| Filename                  | Source                                                         |
| ------------------------- | -------------------------------------------------------------- |
| `pagerduty_routing_key`   | PagerDuty service → Integrations → Events API v2 routing key   |
| `slack_webhook_url`       | Slack app → Incoming Webhook URL for the `#docflow-alerts` channel |

Until you create these files Alertmanager keeps routing alerts to
the local `alertmanager_sink` container so nothing is silently
dropped — `docker compose logs -f alertmanager_sink` shows every
fired alert as the JSON payload Alertmanager would have posted.

After adding or rotating a secret, reload without a restart:

```bash
curl -X POST http://localhost:9093/-/reload
```

In Kubernetes, mount the same paths from a Secret and rotate via
`kubectl create secret generic --dry-run | kubectl apply -f -`.
