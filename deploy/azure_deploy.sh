#!/usr/bin/env bash
# Azure deployment. You run this yourself (not automated) — review each
# section before running. Requires: az CLI logged in (`az login`), docker,
# and a GHCR image already pushed (see "1. Build & push image" below) OR
# run that section first too.
#
# Architecture (as actually deployed and verified, not the original plan —
# see the notes on each section below for what changed and why):
#   - Azure Container Apps environment (consumption plan — this stays under
#     the Always Free monthly grant for a low-traffic demo).
#   - ONE container app (fleetguard-app) running TWO containers in the same
#     pod: a plain `postgres:16` container and the FleetGuard API container,
#     talking to each other over `localhost` (a "sidecar" pattern). This is
#     a deliberate change from the original two-separate-apps design — see
#     Section 5's note for the two real bugs that forced it.
#   - Postgres uses the container's own ephemeral local storage, not a
#     persistent volume — also a deliberate change, see Section 5.
#   - The FleetGuard API/Postgres image pulls from GHCR (free for a public
#     image, avoids Azure Container Registry's ~$5/month Basic tier — not
#     covered by any free grant).
#   - The image's own entrypoint (docker-entrypoint.sh) waits for Postgres,
#     seeds the DB automatically if empty, then starts uvicorn — replaces
#     the originally-planned separate one-off seed step (see Section 6).
#
# Cost note: because Postgres and the API now share one container app, that
# whole app runs at --min-replicas 1 (no scale-to-zero) — the combined app
# is what stays up continuously for the deploy-and-screenshot window, not
# just a small Postgres-only footprint as in the original plan. Still a
# single small container app on the consumption plan; tear down the
# resource group once screenshots are captured to stop it accruing.
set -euo pipefail

# ---- 0. Config — edit these ----
RESOURCE_GROUP="fleetguard-rg"
LOCATION="germanywestcentral"              # westeurope rejected new-customer signups outright
                                            # (RequestDisallowedByAzure) on this account at deploy
                                            # time — some popular regions do this independent of
                                            # quota; germanywestcentral accepted it, still low-
                                            # latency for a Germany-based account.
ENV_NAME="fleetguard-env"
API_APP="fleetguard-app"

GITHUB_USER="Prennoy99"
# Docker/OCI image references must be all-lowercase (unlike GitHub usernames,
# which are case-insensitive) — ghcr.io/Prennoy99/... is rejected outright.
IMAGE="ghcr.io/${GITHUB_USER,,}/fleetguard:latest"

# Secrets — do NOT commit real values anywhere. Export these in your shell
# before running this script, e.g.:
#   export FG_GEMINI_API_KEY=... FG_API_KEY=... FG_PG_PASSWORD=...
: "${FG_GEMINI_API_KEY:?set FG_GEMINI_API_KEY in your shell first}"
: "${FG_API_KEY:?set FG_API_KEY in your shell first}"
: "${FG_PG_PASSWORD:?set FG_PG_PASSWORD in your shell first}"


# ---- 1. Build & push the image to GHCR (skip if already pushed) ----
# docker build -t "$IMAGE" .
# echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin
# docker push "$IMAGE"
# After the first push: on github.com -> your profile -> Packages -> fleetguard
# -> Package settings -> change visibility to Public (defaults to private,
# which would otherwise need a pull secret / count against private limits).


# ---- 2. Resource group ----
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"


# ---- 3. Container Apps environment ----
# NOTE: `az containerapp create --yaml` (the natural way to submit a full
# manifest) is broken against this account's environment: the `containerapp`
# CLI extension (tested at 1.3.0b4, preview) targets a preview ARM API
# version (2025-10-02-preview) that rejects a well-formed, correctly-
# substituted manifest with an opaque `400 "The JSON value could not be
# converted to System.Boolean. Path: $ | LineNumber: 0 | BytePositionInLine:
# 4."` — reproduced identically across multiple manifest variants, so it's a
# bug in that preview API surface, not a manifest content problem. Every
# container app / job create+update below goes through `az rest` against the
# stable, GA `2024-03-01` API version instead, bypassing the extension's
# buggy request-building path entirely. Environment creation itself still
# uses the plain CLI command since that path isn't affected.
az extension add --name containerapp --upgrade -y
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.Storage

az containerapp env create \
  --name "$ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION"

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
ENV_ID=$(az containerapp env show \
  --name "$ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query id -o tsv)


# ---- 4. FleetGuard app: Postgres + API as two containers, one pod ----
# ORIGINAL PLAN (reverted): Postgres as its own container app, internal TCP
# ingress, Azure Files volume for persistence. Two real, independently-
# confirmed bugs killed that design on a live deploy:
#   1. Azure Files is SMB-backed, and SMB does not support the POSIX chmod/
#      locking operations Postgres's initdb needs on its data directory —
#      Postgres crash-looped forever with "chmod: ... Operation not
#      permitted", never actually starting.
#   2. Independently, Container Apps' internal TCP ingress did not route
#      traffic at all in this environment/account — confirmed by both a
#      one-off Job AND the long-running API container timing out trying to
#      reach Postgres's internal FQDN on port 5432, even after Postgres was
#      confirmed healthy and listening.
# Fix: merge Postgres into the API app as a second container in the same
# pod. Containers in one Container Apps pod share `localhost`, which
# sidesteps both bugs entirely — no volume (ephemeral storage instead, see
# the cost/architecture note above), no inter-app ingress at all.
cat > /tmp/fleetguard-app.json <<JSON
{
  "location": "${LOCATION}",
  "properties": {
    "environmentId": "${ENV_ID}",
    "configuration": {
      "ingress": {
        "external": true,
        "targetPort": 8000,
        "transport": "auto"
      },
      "secrets": [
        {"name": "database-url", "value": "postgresql://fleetguard:${FG_PG_PASSWORD}@localhost:5432/fleetguard"},
        {"name": "pg-password", "value": "${FG_PG_PASSWORD}"},
        {"name": "gemini-api-key", "value": "${FG_GEMINI_API_KEY}"},
        {"name": "api-key", "value": "${FG_API_KEY}"}
      ]
    },
    "template": {
      "containers": [
        {
          "image": "postgres:16",
          "name": "postgres",
          "env": [
            {"name": "POSTGRES_USER", "value": "fleetguard"},
            {"name": "POSTGRES_PASSWORD", "secretRef": "pg-password"},
            {"name": "POSTGRES_DB", "value": "fleetguard"}
          ],
          "resources": {"cpu": 0.5, "memory": "1.0Gi"}
        },
        {
          "image": "${IMAGE}",
          "name": "fleetguard-app",
          "env": [
            {"name": "DATABASE_URL", "secretRef": "database-url"},
            {"name": "GEMINI_API_KEY", "secretRef": "gemini-api-key"},
            {"name": "GEMINI_MODEL", "value": "gemini-3.1-flash-lite"},
            {"name": "API_KEY", "secretRef": "api-key"}
          ],
          "resources": {"cpu": 0.5, "memory": "1.0Gi"}
        }
      ],
      "scale": {"minReplicas": 1, "maxReplicas": 1}
    }
  }
}
JSON

az rest --method put \
  --uri "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.App/containerApps/${API_APP}?api-version=2024-03-01" \
  --body @/tmp/fleetguard-app.json

for i in $(seq 1 18); do
  STATE=$(az rest --method get \
    --uri "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.App/containerApps/${API_APP}?api-version=2024-03-01" \
    --query "properties.provisioningState" -o tsv)
  echo "fleetguard-app provisioning: $STATE"
  [ "$STATE" = "Succeeded" ] || [ "$STATE" = "Failed" ] && break
  sleep 10
done

APP_FQDN=$(az rest --method get \
  --uri "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.App/containerApps/${API_APP}?api-version=2024-03-01" \
  --query "properties.configuration.ingress.fqdn" -o tsv)
echo "FleetGuard API live at: https://$APP_FQDN"
echo "Health check: curl https://$APP_FQDN/health"


# ---- 5. Seeding the database ----
# ORIGINAL PLAN (reverted): a one-off Container Apps Job running
# `python -m generator.generate` against Postgres after both apps were up.
# Once Postgres moved into the same pod as the API container (Section 4),
# a separate Job no longer shares `localhost` with it — Jobs run in their
# own pod, so this approach stopped being reachable at all.
# Fix: the image's own entrypoint (docker-entrypoint.sh) now waits for
# Postgres to accept connections, checks whether telemetry_raw is empty,
# and runs the generator itself before starting uvicorn — idempotent and
# automatic on every container start, no manual seed step needed.


# ---- 6. Teardown (run once screenshots are captured) ----
# az group delete --name "$RESOURCE_GROUP" --yes --no-wait
# Then cancel the Azure subscription, then remove the card — removing a card
# generally requires the subscription to be cancelled first, not just the
# resources deleted. Verify exact current portal steps at that time.
