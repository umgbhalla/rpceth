# Security

## Credentials

Use placeholders in committed configuration and documentation. Keep actual RPC provider credentials and the gateway API key in your local configuration or deployment secret store. The current executable reads `config/proxy.yaml`; it does not automatically expand environment variables in that file.

The sample gateway key and Grafana login are development defaults. Replace them before deployment. Provider URL credentials can appear in application logs and admin responses; restrict access and configure redaction at your ingress and log collector.

## Check before publication

Run both scans from the repository root with [Gitleaks](https://github.com/gitleaks/gitleaks) installed:

```sh
# All locally available Git refs, including previous file versions.
GOMAXPROCS=2 gitleaks git . --log-opts="--all" --redact=100

# Current files, including documentation that is not committed yet.
GOMAXPROCS=2 gitleaks dir . --redact=100
```

The repository configuration extends Gitleaks' default rules with detection for NodeReal credentials embedded in RPC URLs. A passing scan is evidence from those rules, not a guarantee that all possible secrets have been found. Review provider URLs and deployment configuration separately.

If a real credential has been committed, revoke or rotate it with its provider. Deleting it in a new commit does not remove earlier copies. Rewriting history does not revoke it and cannot remove copies from existing clones, forks, caches, or retained GitHub objects.

## Runtime exposure

- The executable binds to `0.0.0.0:3000`.
- RPC requests authenticate using an `apikey` query parameter. URLs can be logged by clients, proxies, and servers.
- Admin, readiness, liveness, and metrics endpoints are outside RPC authentication. Protect these at the network or ingress layer.
- The Docker Compose stack is for local development. It exposes monitoring ports and includes default Grafana credentials.

Publishing source code and safely exposing a running gateway are separate reviews. See [architecture boundaries](docs/architecture.md#current-boundaries) for other implementation details.

## Reporting an issue

Do not post credentials or private deployment details in public issues. Revoke an exposed credential first, then contact the repository owner privately with a redacted description and affected file locations.
