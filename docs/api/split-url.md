# Server-Side Split URL Testing API

!!! info "Part of the `split_url` module"
    Split URL testing is one of the optional modules -- present in the **full profile**, absent from the core one. A core deployment does not serve these routes. See [Modules and profiles](../getting-started/modules.md) for what each profile includes and how to run the full one.

This document describes the server-side split URL testing feature. Split URL experiments redirect different user segments to distinct URLs (e.g., `/checkout-v1` vs `/checkout-v2`) using Lambda@Edge at the CloudFront layer, providing zero-latency variant delivery and persistent cookie-based assignment.

---

## Overview

Split URL testing differs from classic A/B tests in that the **entire page or URL path** varies between variants rather than a component within a single page. The platform implements this at the CDN edge using **Lambda@Edge**, which:

1. Reads the user's assignment cookie (`exp_{experiment_key}`).
2. If no cookie exists, performs consistent-hash bucketing to assign a variant.
3. Redirects the request (`302`) to the variant URL.
4. Sets a `1-year` persistence cookie so the user always sees the same variant.

---

## Experiment Type

Set `experiment_type` to `SPLIT_URL` when creating or updating an experiment.

### `SplitUrlConfig` Schema

The `split_url_config` field is required when `experiment_type` is `SPLIT_URL`.

| Field | Type | Required | Description |
|---|---|---|---|
| `variants` | `array` | Yes | List of variant URL assignments (minimum 2, maximum 10) |
| `variants[].url` | `string` | Yes | Fully-qualified URL or path for this variant (e.g., `https://example.com/checkout-v2`) |
| `variants[].weight` | `int` | Yes | Traffic weight for this variant (0-100; all weights must sum to exactly 100) |

**Variant key**: The `key` field on each experiment variant maps to the corresponding `variants[]` entry by position. The first variant is always treated as the control.

---

## Create a Split URL Experiment

```
POST /api/v1/experiments/
```

**Example Request**

```bash
curl -X POST "https://your-platform.example.com/api/v1/experiments/" \
  -H "Authorization: Bearer your_access_token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Checkout Flow Split URL Test",
    "hypothesis": "The new checkout URL reduces drop-off by 10%",
    "experiment_type": "SPLIT_URL",
    "split_url_config": {
      "variants": [
        { "url": "https://example.com/checkout",    "weight": 50 },
        { "url": "https://example.com/checkout-v2", "weight": 50 }
      ]
    },
    "variants": [
      { "key": "control",   "name": "Original Checkout", "weight": 0.5 },
      { "key": "treatment", "name": "New Checkout",      "weight": 0.5 }
    ],
    "start_date": "2026-03-10T00:00:00Z",
    "end_date":   "2026-04-10T00:00:00Z"
  }'
```

**Response: 201 Created**

```json
{
  "id": "exp-uuid-here",
  "name": "Checkout Flow Split URL Test",
  "experiment_type": "SPLIT_URL",
  "status": "DRAFT",
  "split_url_config": {
    "variants": [
      { "url": "https://example.com/checkout",    "weight": 50 },
      { "url": "https://example.com/checkout-v2", "weight": 50 }
    ]
  },
  "variants": [
    { "key": "control",   "name": "Original Checkout", "weight": 0.5 },
    { "key": "treatment", "name": "New Checkout",      "weight": 0.5 }
  ],
  "created_at": "2026-03-02T12:00:00Z",
  "updated_at": "2026-03-02T12:00:00Z"
}
```

---

## Split URL Preview Endpoint

```
GET /api/v1/experiments/{experiment_id}/split-url/preview
```

Returns the variant assignment and redirect URL for a given user, without performing an actual redirect. Use this endpoint during development and QA to verify bucketing logic.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `experiment_id` | `string` (UUID) | The experiment to preview |

**Query Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user_id` | `string` | Yes | User identifier to use for consistent-hash bucketing |
| `attributes` | `object` | No | Optional targeting attributes as a JSON object (URL-encoded) |

**Example Request**

```bash
curl -X GET "https://your-platform.example.com/api/v1/experiments/exp-uuid-here/split-url/preview?user_id=alice" \
  -H "Authorization: Bearer your_access_token"
```

**Response: 200 OK**

```json
{
  "experiment_id": "exp-uuid-here",
  "experiment_key": "checkout-flow-split-url-test",
  "user_id": "alice",
  "assigned_variant": "treatment",
  "redirect_url": "https://example.com/checkout-v2",
  "cookie_name": "exp_checkout-flow-split-url-test",
  "cookie_value": "treatment",
  "cookie_max_age_seconds": 31536000
}
```

---

## Lambda@Edge Cookie and Redirect Flow

The Lambda@Edge function runs on every CloudFront `viewer-request` event for the configured distribution. The flow is:

```
User Request
     |
     v
Lambda@Edge (viewer-request)
     |
     +-- Read cookie: exp_{experiment_key}
     |        |
     |        +-- Cookie present --> use stored variant
     |        |
     |        +-- Cookie absent  --> consistent-hash bucket(user_id)
     |                                  --> assign variant
     |
     +-- Determine redirect URL from split_url_config
     |
     +-- Return 302 response with:
           Location: <variant_url>
           Set-Cookie: exp_{experiment_key}=<variant_key>; Max-Age=31536000; Path=/; Secure; SameSite=Lax
```

### Cookie Details

| Property | Value |
|---|---|
| **Cookie name** | `exp_{experiment_key}` where `experiment_key` is the URL-safe slug of the experiment (e.g., `exp_checkout-flow-split-url-test`) |
| **Cookie value** | The variant key (e.g., `control`, `treatment`) |
| **Max-Age** | `31536000` seconds (1 year) |
| **Path** | `/` |
| **Secure** | Set; only transmitted over HTTPS |
| **SameSite** | `Lax` |

### Redirect Details

| Property | Value |
|---|---|
| **HTTP status** | `302 Found` |
| **Location header** | The `url` field from the assigned variant in `split_url_config` |
| **Cache-Control** | `no-store` (redirects must not be cached by intermediate proxies) |

### Cookie Persistence

Once a user receives the `Set-Cookie` header, their browser stores the assignment for 1 year. On all subsequent visits, Lambda@Edge reads the cookie and redirects to the same URL without re-bucketing. This ensures:

- Consistent user experience throughout the experiment.
- No re-assignment when the user clears browser cache (only when cookies are cleared).
- Cross-session persistence within the same browser.

---

## CloudFront CDK Construct

The CDK construct (`infrastructure/constructs/SplitUrlDistribution`) provisions:

1. A CloudFront distribution attached to your origin (ALB or S3).
2. A Lambda@Edge function deployed to `us-east-1` (required for Lambda@Edge).
3. An environment variable (`EXPERIMENTATION_API_URL`) injected into the Lambda to fetch the live `split_url_config` at cold start and cache it for 60 seconds.

**CDK Usage** (`infrastructure/app.ts`):

```typescript
import { SplitUrlDistribution } from './constructs/SplitUrlDistribution';

new SplitUrlDistribution(this, 'CheckoutSplitUrl', {
  experimentKey: 'checkout-flow-split-url-test',
  originDomainName: alb.loadBalancerDnsName,
  experimentationApiUrl: 'https://your-platform.example.com',
  experimentationApiKey: apiKeySecret.secretValue.toString(),
});
```

---

## Validation Rules

- All `weight` values in `split_url_config.variants` must be integers in the range `[0, 100]`.
- The sum of all weights must equal exactly `100`.
- Each `url` must be a valid absolute URL or an absolute path starting with `/`.
- The number of entries in `split_url_config.variants` must match the number of `variants` on the experiment.
- `experiment_type` must be `SPLIT_URL` for `split_url_config` to be accepted.

---

## Error Responses

| Status | Meaning |
|---|---|
| `400 Bad Request` | Weights do not sum to 100, URL is invalid, variant count mismatch |
| `401 Unauthorized` | Missing or invalid Bearer token |
| `403 Forbidden` | Insufficient role |
| `404 Not Found` | Experiment ID does not exist or experiment is not of type `SPLIT_URL` |
| `422 Unprocessable Entity` | Schema validation failure |

```json
{
  "detail": "split_url_config variant weights must sum to 100, got 95"
}
```
