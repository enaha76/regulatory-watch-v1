# Secrets handling

This document describes how secrets are sourced in each environment and
the contracts the codebase relies on. It exists so a security review
can answer "where does `OPENAI_API_KEY` come from in production?"
without grepping the repo.

## TL;DR

| Environment | Source                                  | Rotation        | Notes                                         |
|-------------|-----------------------------------------|-----------------|-----------------------------------------------|
| Dev (laptop)| `.env` file (git-ignored)               | Manual          | Loaded by `pydantic-settings`                 |
| CI          | GitHub Actions encrypted secrets        | On compromise   | Injected as env vars only for the job that needs them |
| Staging     | AWS Secrets Manager  or  Vault          | 90 days         | Mounted by ECS / k8s as env vars at boot      |
| Production  | AWS Secrets Manager  or  Vault          | 30 days         | Same mechanism as staging; separate vault path|

The application itself does **NOT** read from a vault directly. All
secret material reaches the process as environment variables, which
`pydantic-settings` then validates. This keeps the code path identical
across environments and avoids a vault-client dependency in the runtime.

## Settings precedence

`app.config.Settings` resolves a value in this order (highest first):

1. **Real environment variables** — what production uses.
2. **`.env` file** — convenient for local dev, **never present in
   production images**. The Dockerfile does not COPY `.env`.
3. **Defaults declared in `app/config.py`** — production-safe baselines.

This is the standard `pydantic-settings` precedence; it is documented
here because it implies an important property: **a production
deployment cannot accidentally inherit a developer's secret** even if
a `.env` file leaks into a build context, because env vars override.

## Sensitive fields

| Field                       | Used by                          | Required |
|-----------------------------|----------------------------------|----------|
| `OPENAI_API_KEY`            | `app.services.significance`, `app.services.obligations`, web LLM fallback | yes (else LLM features no-op) |
| `AWS_ACCESS_KEY_ID`         | `app.ingestion.storage` (S3)     | optional |
| `AWS_SECRET_ACCESS_KEY`     | `app.ingestion.storage` (S3)     | optional |
| `IMAP_PASSWORD`             | `app.ingestion.email_connector`  | optional |
| `DATABASE_URL` (when remote)| Engine bootstrap                 | yes      |

All of these are **read once at process start** by the cached
`get_settings()` singleton. To rotate a secret in a running deployment
you must restart the process. There is no in-process refresh path —
that would couple the runtime to a specific vault client and is out of
scope for the current architecture.

## Operational rules

* **Never** commit a `.env` file. The repo `.gitignore` excludes
  `.env*` patterns; CI also runs `git secrets`-style scans.
* **Never** log raw secrets. The `app.logging_setup` JSON renderer
  emits whole field dicts — anything you `log.bind()` ends up in log
  storage. Treat secret values like PII.
* **Per-environment separation.** Production and staging use **distinct
  API keys** so a leak in staging does not compromise production
  budgets / rate limits.
* **Limit blast radius.** The `OPENAI_API_KEY` is scoped via the
  OpenAI dashboard to: `gpt-4o-mini` only, with a hard monthly USD cap.
* **Rotation.** All keys ship with a documented rotation cadence (see
  table above). Operators rotate by:
    1. Creating a new key in the provider console.
    2. Updating the secret value in AWS Secrets Manager / Vault.
    3. Triggering a rolling restart of the service (or letting the
       next deploy pick it up).
    4. Revoking the old key after 24h grace.

## Bootstrap example: AWS ECS task definition (Fargate)

```jsonc
{
  "containerDefinitions": [
    {
      "name": "regwatch-api",
      "image": "ghcr.io/your-org/regwatch:1.2.3",
      "secrets": [
        { "name": "OPENAI_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:eu-west-1:123:secret:regwatch/prod/openai-Ab12Cd" },
        { "name": "AWS_SECRET_ACCESS_KEY",
          "valueFrom": "arn:aws:secretsmanager:eu-west-1:123:secret:regwatch/prod/s3-Ef34Gh" }
      ],
      "environment": [
        { "name": "APP_ENV", "value": "prod" },
        { "name": "LOG_FORMAT", "value": "json" },
        { "name": "DEV_AUTOCREATE_TABLES", "value": "false" }
      ]
    }
  ]
}
```

ECS injects each `secrets[]` entry as a real env var at container start
— no plaintext secret hits the container image, the task definition, or
the application disk.

## Bootstrap example: Kubernetes (External Secrets Operator)

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: regwatch-runtime
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets-manager
  target:
    name: regwatch-runtime
  data:
    - secretKey: OPENAI_API_KEY
      remoteRef: { key: regwatch/prod/openai }
    - secretKey: AWS_SECRET_ACCESS_KEY
      remoteRef: { key: regwatch/prod/s3 }
```

Mount the resulting Secret as `envFrom:` on the deployment's pod spec.
