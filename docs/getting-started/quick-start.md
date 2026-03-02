# Quick Start Guide

Get from zero to your first running experiment in under 30 minutes.

---

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.9+ | `python --version` |
| Node.js | 18+ | `node --version` |
| Docker + Compose | 24+ | `docker --version` |
| Git | Any | `git --version` |

---

## Step 1: Clone and Configure

```bash
git clone https://github.com/amarkanday/experimentation-platform.git
cd experimentation-platform
cp backend/.env.example backend/.env
```

Edit `backend/.env`:

```env
# Database
POSTGRES_SERVER=localhost
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=experimentation
POSTGRES_SCHEMA=experimentation

# Security (change in production!)
SECRET_KEY=your-secret-key-min-32-chars
ACCESS_TOKEN_EXPIRE_MINUTES=30

# App
APP_ENV=development
DEBUG=true
```

---

## Step 2: Start the Platform

```bash
# Start PostgreSQL + Redis
docker-compose up -d db redis

# Verify services are healthy
docker-compose ps
```

Expected output:
```
NAME                STATUS
experimentation-db  Up (healthy)
experimentation-redis  Up
```

---

## Step 3: Set Up Backend

```bash
# Create and activate virtualenv
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
cd backend
pip install -r requirements.txt

# Run database migrations
export POSTGRES_DB=experimentation POSTGRES_SCHEMA=experimentation
python -m alembic -c app/db/alembic.ini upgrade head

# Start the API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verify: open http://localhost:8000/health — should return `{"status": "ok"}`.

Interactive API docs: http://localhost:8000/docs

---

## Step 4: Set Up Frontend

Open a new terminal:

```bash
cd frontend
npm install
npm run dev
```

Verify: open http://localhost:3000

---

## Step 5: Create Your First Experiment

### Option A: Via the UI

1. Open http://localhost:3000
2. Click **Experiments** → **New Experiment**
3. Fill in:
   - Name: `Homepage Button Color Test`
   - Key: `homepage-button-color` (auto-generated)
   - Hypothesis: "A green CTA button will increase click-through rate"
4. Add variants:
   - **Control** (50% traffic) — existing blue button
   - **Treatment** (50% traffic) — new green button
5. Add a metric: `click` event, primary metric
6. Click **Create** → **Start Experiment**

### Option B: Via the API

```bash
# 1. Login to get a token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' \
  | jq -r '.access_token')

# 2. Create an experiment
curl -X POST http://localhost:8000/api/v1/experiments \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Homepage Button Color Test",
    "key": "homepage-button-color",
    "description": "Test green vs blue CTA button",
    "hypothesis": "Green button increases CTR",
    "type": "A_B",
    "variants": [
      {"name": "Control", "is_control": true, "traffic_allocation": 50},
      {"name": "Treatment", "is_control": false, "traffic_allocation": 50}
    ],
    "metrics": [
      {"name": "Click Rate", "event_name": "click", "metric_type": "CONVERSION", "is_primary": true}
    ]
  }'

# 3. Start the experiment (replace EXPERIMENT_ID)
curl -X POST http://localhost:8000/api/v1/experiments/EXPERIMENT_ID/start \
  -H "Authorization: Bearer $TOKEN"
```

---

## Step 6: Track Events from Your Application

Once your experiment is running, integrate event tracking. All tracking endpoints use an **API key** (not a user token).

### Get your API key

```bash
curl -X POST http://localhost:8000/api/v1/auth/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-app-key", "description": "Frontend app key"}'
```

### Assign a user to the experiment

```javascript
const response = await fetch('http://localhost:8000/api/v1/tracking/assign', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': 'your-api-key',
  },
  body: JSON.stringify({
    user_id: 'user-123',
    experiment_key: 'homepage-button-color',
    context: { country: 'US', device: 'mobile' },
  }),
});
const { variant_name, configuration } = await response.json();
// variant_name = "Control" or "Treatment"
// Use this to show the right variant to the user
```

### Track a conversion event

```javascript
await fetch('http://localhost:8000/api/v1/tracking/track', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': 'your-api-key',
  },
  body: JSON.stringify({
    event_type: 'click',
    user_id: 'user-123',
    experiment_key: 'homepage-button-color',
    value: 1.0,
  }),
});
```

---

## Step 7: View Results

Once you have collected sufficient data:

1. Open http://localhost:3000/results/EXPERIMENT_ID
2. The dashboard shows:
   - Conversion rates per variant
   - Statistical significance (p-value)
   - Effect size and confidence intervals
   - Sample size adequacy meter
   - Recommendation: Ship / Keep Control / Continue Testing

Or via API:

```bash
curl http://localhost:8000/api/v1/results/EXPERIMENT_ID \
  -H "Authorization: Bearer $TOKEN"
```

---

## Step 8: Create a Feature Flag

Feature flags let you control rollouts without deploying new code.

```bash
# Create a feature flag
curl -X POST http://localhost:8000/api/v1/feature-flags \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "new-checkout-flow",
    "name": "New Checkout Flow",
    "description": "Redesigned checkout experience",
    "rollout_percentage": 0
  }'

# Activate it for 10% of users
curl -X PUT http://localhost:8000/api/v1/feature-flags/FLAG_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"rollout_percentage": 10, "status": "ACTIVE"}'
```

Evaluate the flag in your frontend:

```javascript
const flagResponse = await fetch(
  `http://localhost:8000/api/v1/feature-flags/new-checkout-flow/evaluate`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': 'your-api-key' },
    body: JSON.stringify({ user_id: 'user-123', context: {} }),
  }
);
const { enabled } = await flagResponse.json();

if (enabled) {
  showNewCheckoutFlow();
} else {
  showCurrentCheckoutFlow();
}
```

---

## What's Next?

- [Technical Guide](../architecture/technical-guide.md) — Deep dive into the platform architecture
- [User Guide](../guides/user-guide.md) — Guide for experiment designers and analysts
- [Testing Guide](../development/testing-guide.md) — Write and run tests
- [API Reference](http://localhost:8000/docs) — Interactive API documentation
- [SDK Documentation](../sdk/) — JavaScript and Python SDK guides

---

## Troubleshooting

**Backend won't start:**
```bash
# Check PostgreSQL is running
docker-compose ps
# Check logs
docker-compose logs db
# Re-run migrations
python -m alembic -c app/db/alembic.ini upgrade head
```

**`ModuleNotFoundError`:**
```bash
# Virtualenv not activated
source venv/bin/activate
pip install -r requirements.txt
```

**Frontend shows blank page:**
```bash
# Check backend is running
curl http://localhost:8000/health
# Check env vars
cat frontend/.env.local
# NEXT_PUBLIC_API_URL=http://localhost:8000
```

**Tracking events not recorded:**
- Verify your API key is valid: `curl -H "X-API-Key: KEY" http://localhost:8000/api/v1/tracking/`
- Confirm the experiment is in `ACTIVE` status
- Confirm the `experiment_key` matches exactly (case-sensitive)
