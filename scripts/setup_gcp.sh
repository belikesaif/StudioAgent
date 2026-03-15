#!/bin/bash
# StudioAgent - Google Cloud Platform Setup Script
# Run this once to configure your GCP project

set -euo pipefail

echo "=== StudioAgent GCP Setup ==="

# Configuration (edit these or set env vars)
PROJECT_ID="${GCP_PROJECT_ID:-studioagent-$(date +%s)}"
REGION="us-central1"
BUCKET_NAME="studioagent-videos-${PROJECT_ID}"

echo "Project ID: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Bucket: ${BUCKET_NAME}"

# Step 1: Create project (or use existing)
echo ""
echo "--- Creating/selecting GCP project ---"
gcloud projects create "${PROJECT_ID}" --name="StudioAgent" 2>/dev/null || true
gcloud config set project "${PROJECT_ID}"

# Step 2: Enable billing (manual step)
echo ""
echo "ACTION REQUIRED: Enable billing for project ${PROJECT_ID}"
echo "Visit: https://console.cloud.google.com/billing/linkedaccount?project=${PROJECT_ID}"
echo "Press Enter when billing is enabled..."
read

# Step 3: Enable required APIs
echo ""
echo "--- Enabling APIs ---"
gcloud services enable \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    storage.googleapis.com \
    artifactregistry.googleapis.com

# Step 4: Create Cloud Storage bucket
echo ""
echo "--- Creating GCS bucket ---"
gsutil mb -p "${PROJECT_ID}" -l "${REGION}" "gs://${BUCKET_NAME}" 2>/dev/null || true

# Set CORS for web uploads
cat > /tmp/cors.json << 'CORS'
[
  {
    "origin": ["*"],
    "method": ["GET", "PUT", "POST", "DELETE"],
    "responseHeader": ["Content-Type", "Authorization"],
    "maxAgeSeconds": 3600
  }
]
CORS
gsutil cors set /tmp/cors.json "gs://${BUCKET_NAME}"

# Step 5: Create service account for Cloud Run
echo ""
echo "--- Creating service account ---"
SA_NAME="studioagent-runner"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="StudioAgent Cloud Run Service Account" 2>/dev/null || true

# Grant Storage access
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectAdmin"

# Step 6: Create service account key for local development
echo ""
echo "--- Creating service account key ---"
gcloud iam service-accounts keys create "./service-account.json" \
    --iam-account="${SA_EMAIL}"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Add these to your .env file:"
echo "  GCP_PROJECT_ID=${PROJECT_ID}"
echo "  GCS_BUCKET_NAME=${BUCKET_NAME}"
echo "  GOOGLE_APPLICATION_CREDENTIALS=./service-account.json"
echo ""
echo "Get a Gemini API key at: https://aistudio.google.com/apikey"
echo "  GEMINI_API_KEY=your-key-here"
echo ""
echo "To run locally:"
echo "  pip install -r requirements.txt"
echo "  uvicorn app.main:app --reload --port 8080"
echo ""
echo "To deploy to Cloud Run:"
echo "  gcloud builds submit --config=cloudbuild.yaml"
