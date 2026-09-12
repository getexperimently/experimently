# Lambda Functions for Real-time Services

This directory contains AWS Lambda functions for high-performance, real-time experiment assignment and event processing.

## 📁 Structure

```
backend/lambda/
├── shared/                    # Shared utilities and models
│   ├── __init__.py
│   ├── consistent_hash.py    # Consistent hashing for assignments
│   ├── models.py             # Pydantic data models
│   └── utils.py              # Common utilities (logging, AWS helpers)
│
├── assignment/               # Experiment assignment Lambda
│   ├── handler.py           # Main handler (TODO)
│   ├── requirements.txt
│   └── tests/
│
├── events/                  # Event processor Lambda
│   ├── handler.py          # Main handler (TODO)
│   ├── requirements.txt
│   └── tests/
│
└── feature_flags/          # Feature flag evaluation Lambda
    ├── handler.py         # Main handler (TODO)
    ├── requirements.txt
    └── tests/
```

## 🎯 Lambda Functions

### 1. Assignment Lambda
**Purpose:** Real-time experiment variant assignment using consistent hashing

**Performance Targets:**
- P50 latency: < 20ms
- P99 latency: < 50ms
- Throughput: 10K requests/second

**Key Features:**
- Deterministic assignments (same user + experiment = same variant)
- Respects traffic allocation
- Evaluates targeting rules
- Stores assignments in DynamoDB

### 2. Event Processor Lambda
**Purpose:** Process incoming events from Kinesis stream

**Performance Targets:**
- Batch processing: 100-500 events
- Processing latency: < 100ms per batch
- Error rate: < 0.1%

**Key Features:**
- Validates and enriches events
- Aggregates real-time metrics
- Archives to S3 via Firehose
- Handles partial batch failures

### 3. Feature Flag Evaluation Lambda
**Purpose:** Real-time feature flag evaluation with targeting

**Performance Targets:**
- P50 latency: < 15ms
- P99 latency: < 40ms
- Cache hit rate: > 95%

**Key Features:**
- Evaluates targeting rules
- Applies rollout percentages
- Caches flag configurations
- Records evaluation events

## 🔧 Shared Utilities

### Consistent Hashing (`consistent_hash.py`)

Implements MurmurHash3-style hashing for deterministic variant assignment:

```python
from shared import ConsistentHasher

hasher = ConsistentHasher()
variant = hasher.assign_variant(
    user_id="user_123",
    experiment_key="checkout_redesign",
    variants=[
        {"key": "control", "allocation": 0.5},
        {"key": "treatment", "allocation": 0.5},
    ],
    traffic_allocation=1.0,
)
# Returns: "control" or "treatment" deterministically
```

### Data Models (`models.py`)

Pydantic models for type safety and validation:

- `Assignment` - Experiment assignment data
- `ExperimentConfig` - Experiment configuration
- `FeatureFlagConfig` - Feature flag configuration
- `EventData` - Incoming event data
- `LambdaResponse` - Standard response format

### Utilities (`utils.py`)

Common helper functions:

- `get_logger()` - Structured JSON logging
- `validate_event()` - Event validation
- `format_response()` - Standard response formatting
- `put_dynamodb_item()` - DynamoDB operations
- `put_kinesis_record()` - Kinesis operations
- `get_env_variable()` - Environment variable management

## 🚀 Deployment

Lambda functions are deployed using AWS CDK:

```bash
cd infrastructure/cdk
cdk deploy --all
```

## 📊 Monitoring

All Lambda functions emit metrics to CloudWatch:

- **Invocations** - Total function invocations
- **Errors** - Error count and rate
- **Duration** - Execution time (P50, P99)
- **ConcurrentExecutions** - Concurrent invocations
- **Custom Metrics** - Business-specific metrics

## 🧪 Testing

Run unit tests:

```bash
pytest backend/lambda/assignment/tests/
pytest backend/lambda/events/tests/
pytest backend/lambda/feature_flags/tests/
```

## 📝 Development Status

- [x] Phase 1: Setup & Infrastructure (COMPLETED)
  - [x] Directory structure created
  - [x] Shared utilities module
  - [x] Consistent hashing algorithm
  - [x] Data models and helpers

- [ ] Phase 2: Assignment Lambda (IN PROGRESS)
- [ ] Phase 3: Event Processor Lambda
- [ ] Phase 4: Feature Flag Lambda
- [ ] Phase 5: Testing & Optimization
- [ ] Phase 6: Deployment & Documentation

## 📚 References

- [AWS Lambda Best Practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)
- [DynamoDB Best Practices](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/best-practices.html)
- [Kinesis Stream Processing](https://docs.aws.amazon.com/streams/latest/dev/building-consumers.html)
- EP-010 Ticket: `docs/tickets/EP-010-lambda-real-time-services.md`
