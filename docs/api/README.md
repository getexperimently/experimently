# API Documentation

This directory contains the API documentation for Experimently.

## Files

1. [API Reference](endpoints.md)
   - Comprehensive guide to using the API
   - Authentication and authorization
   - Usage examples with curl commands
   - Rate limiting and constraints
   - SDK usage examples
   - Framework integrations

2. [API Specification](specs.md)
   - Detailed OpenAPI/Swagger specification
   - Request/response schemas
   - Error codes and handling
   - Pagination details
   - Data types and formats

3. [API Development Guide](api-docs-guide.md)
   - Guidelines for API development
   - Best practices
   - Versioning strategy
   - Testing requirements
   - Documentation standards

4. [API stability and the OpenAPI snapshots](stability.md)
   - `openapi-v1.stable.json` (core profile) and `openapi-v1.full.json` (full profile),
     the checked-in contract the smoke suite compares against
   - Marking a route `x-stability: beta`
   - What to do when a stable route has to change

## Quick Start

1. Get your API key from the platform's Settings page
2. Use the key in your requests:
   ```bash
   curl -H "Authorization: Bearer YOUR_API_KEY" https://api.experimently.example.com/v1/experiments
   ```
3. Check the [API Reference](endpoints.md) for detailed usage examples
4. Refer to the [API Specification](specs.md) for complete endpoint documentation

## Common Tasks

1. **Authentication**
   - [OAuth2 Authentication](endpoints.md#oauth2-authentication)
   - [API Key Authentication](endpoints.md#api-key-authentication)

2. **Experiments**
   - [Creating and managing experiments](endpoints.md#2-managing-experiments)
   - [Variants and metrics](specs.md)
   - [Analysing results](sequential-testing.md) — and
     [Bayesian](bayesian.md), [CUPED](cuped.md),
     [dimensional breakdowns](dimensional-analysis.md)

3. **Feature Flags**
   - [Creating flags and evaluating them](endpoints.md#3-feature-flag-management)
   - [Targeting rules](../Enhanced_Rules_Engine_Reference.md)

4. **Event Tracking**
   - [Tracking events](endpoints.md#4-tracking-events)
   - [Metrics](specs.md)

## Need Help?

- Check the [API Reference](endpoints.md) for usage examples
- Review the [API Specification](specs.md) for detailed endpoint documentation
- Follow the [API Development Guide](api-docs-guide.md) for best practices
- Contact support for additional assistance
