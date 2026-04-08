#!/usr/bin/env bash
# ============================================================
# scripts/deploy.sh — Cloud Run Deployment (Lab 1 pattern)
# ============================================================
set -euo pipefail

if [ -f .env ]; then export $(grep -v '^#' .env | xargs); fi

PROJECT_ID=${GOOGLE_CLOUD_PROJECT:?".env GOOGLE_CLOUD_PROJECT required"}
REGION=${GOOGLE_CLOUD_LOCATION:-us-central1}
SERVICE_NAME="multi-agent-system"
SA_NAME="mas-service-account"
SERVICE_ACCOUNT="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_NAME="mas-repo"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")

echo "▶ [1/6] Enabling APIs..."
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com aiplatform.googleapis.com alloydb.googleapis.com \
  compute.googleapis.com servicenetworking.googleapis.com --project="$PROJECT_ID"

echo "▶ [2/6] Creating Artifact Registry..."
gcloud artifacts repositories create "$REPO_NAME" --repository-format=docker \
  --location="$REGION" --project="$PROJECT_ID" 2>/dev/null || true

echo "▶ [3/6] Setting up service account + IAM..."
gcloud iam service-accounts create "$SA_NAME" \
  --display-name="MAS Service Account" --project="$PROJECT_ID" 2>/dev/null || true
for ROLE in roles/aiplatform.user roles/alloydb.client roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" --role="$ROLE" --quiet
done
# AlloyDB service agent → Vertex AI (Lab 6 pattern)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-alloydb.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user" --quiet

echo "▶ [4/6] Building image with Cloud Build..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
gcloud builds submit . --tag="$IMAGE" --project="$PROJECT_ID" --region="$REGION"

echo "▶ [5/6] Deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --image="$IMAGE" --platform=managed --region="$REGION" \
  --service-account="$SERVICE_ACCOUNT" \
  --no-allow-unauthenticated \
  --min-instances=0 --max-instances=10 --concurrency=80 \
  --cpu=2 --memory=2Gi --timeout=300 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=1,MODEL=${MODEL:-gemini-2.5-flash},MCP_TOOLBOX_URL=${MCP_TOOLBOX_URL:-http://mcp-toolbox:5000},ALLOYDB_HOST=${ALLOYDB_HOST:-127.0.0.1},ALLOYDB_DB=${ALLOYDB_DB:-postgres},ALLOYDB_USER=${ALLOYDB_USER:-postgres}" \
  --set-secrets="ALLOYDB_PASSWORD=alloydb-password:latest" \
  --labels="app=${SERVICE_NAME},env=production" \
  --project="$PROJECT_ID"

echo "▶ [6/6] Done!"
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" \
  --format="value(status.url)" --project="$PROJECT_ID")
echo ""
echo "  ✅ Service URL : $SERVICE_URL"
echo "  📖 API Docs   : $SERVICE_URL/docs"
echo "  ❤️  Health    : $SERVICE_URL/health"
