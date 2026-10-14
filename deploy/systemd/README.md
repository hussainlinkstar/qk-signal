# Auto-deploy (systemd timer)

Polls `origin/main` every 60s and runs the smart deployer (`deploy.sh`),
which rebuilds only the service groups whose code changed, health-checks the
backend, and rolls back automatically on failure. No public webhook endpoint
or GCP/Secret Manager dependency is required.

## Install (on the production instance)

```bash
sudo git config --global --add safe.directory /opt/docker/qiko-signal
sudo cp deploy/systemd/qiko-deploy.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now qiko-deploy.timer
```

## Operate

```bash
systemctl list-timers qiko-deploy.timer        # next run
systemctl start qiko-deploy.service            # deploy now
journalctl -u qiko-deploy.service -n 50        # last run logs
```

Manual deploy: `cd /opt/docker/qiko-signal && ./deploy.sh [--force]`
