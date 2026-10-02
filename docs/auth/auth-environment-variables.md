# Authentication Environment Variables

This document provides detailed information about the environment variables required for the AWS Cognito authentication implementation in Experimently.

## Required Cognito Environment Variables

The following environment variables are essential for connecting to and working with AWS Cognito:

| Variable Name | Description | Required | Default |
|---------------|-------------|----------|---------|
| `COGNITO_USER_POOL_ID` | The ID of your AWS Cognito User Pool (e.g., `us-west-2_abcDEF123`) | Yes | None |
| `COGNITO_CLIENT_ID` | The App Client ID for your application | Yes | None |
| `COGNITO_CLIENT_SECRET` | The App Client Secret (if client was created with a secret) | No | None |
| `AWS_REGION` | The AWS region where your Cognito User Pool is deployed | Yes | `us-west-2` |
| `COGNITO_DOMAIN` | Your Cognito domain for hosted UI (if used) | No | None |
| `COGNITO_SELF_SIGNUP_ENABLED` | Under `AUTH_PROVIDER=cognito`, lets anyone who can reach the API register with `POST /api/v1/auth/signup` and `/confirm`. Off: both answer 404 and an administrator creates users ([Adding a user](../cognito_integration.md#adding-a-user)). Ignored under `local`, where both always answer 404. The user pool must also allow self sign-up; the reference pool does not. A self-registered user is in no Cognito group, so their first sign-in creates an account with the Viewer role. | No | `false` |

Under `AUTH_PROVIDER=cognito`, both `COGNITO_USER_POOL_ID` and `COGNITO_CLIENT_ID` are
required. A sign-in, and a call to `/api/v1/auth/me`, is accepted only for an access token
issued to this deployment's user pool (the one `COGNITO_USER_POOL_ID` names) and app client
(`COGNITO_CLIENT_ID`). An ID token, or an access token issued to a different app client, is
refused with a 401. With either setting unset, every sign-in is refused. Keep the pool ID in
the form Cognito gives it, `<region>_<id>` (for example `us-west-2_abcDEF123`): the token
issuer the platform expects is built from it, and a pool ID in any other form refuses every
sign-in. Each refused sign-in is logged at WARNING on the `backend.app.auth.cognito_sign_in`
logger with a `reason` field: `not_configured` when a setting is unset, `wrong_issuer` when
the token was not issued to the configured user pool and app client.

`COGNITO_SELF_SIGNUP_ENABLED` takes `true` or `false`, in any letter case (`1`/`0`, `yes`/`no`,
`on`/`off`, `t`/`f` and `y`/`n` are read the same way). An empty value, or any other value,
stops the API from starting with an error naming the setting. The name must be in upper case: a lower-case
`cognito_self_signup_enabled` is ignored and the setting stays `false`.

**Upgrading from a release where sign-up was always on.** A user who signed up but never
confirmed before this release can no longer confirm through the API while the setting is off.
Confirm them in the user pool with
`aws cognito-idp admin-confirm-sign-up --user-pool-id "$COGNITO_USER_POOL_ID" --username "<their Cognito username>"`,
or delete them and add them again as in [Adding a user](../cognito_integration.md#adding-a-user).

## User pool requirements

The user pool that `COGNITO_USER_POOL_ID` names must require an email address:

- make `email` a **required** standard attribute of the pool;
- if users sign in through a federated identity provider (SAML, OIDC, Google and so on), map
  the provider's email claim to the pool's `email` attribute.

The platform creates a user's account the first time they sign in, and takes the account's
email address from the pool's `email` attribute. A first sign-in from a user with no email
address is refused, and no account is created.
Cognito does not let you change a pool's required attributes after the pool is created, so
set this when you create it. The reference pool in
`infrastructure/cdk/stacks/authentication_stack.py` already requires `email`.

## Additional Configuration Options

These variables provide additional customization for the authentication system:

| Variable Name | Description | Required | Default |
|---------------|-------------|----------|---------|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Duration in minutes that access tokens remain valid | No | `60` (1 hour) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Duration in days that refresh tokens remain valid | No | `30` (30 days) |
| `PASSWORD_MIN_LENGTH` | Minimum length for user passwords | No | `8` |
| `MFA_ENABLED` | Whether Multi-Factor Authentication is required (`true`/`false`) | No | `false` |
| `EMAIL_VERIFICATION_REQUIRED` | Whether email verification is required (`true`/`false`) | No | `true` |
| `COGNITO_CALLBACK_URLS` | Comma-separated list of allowed callback URLs | No | `http://localhost:3000/callback` |
| `COGNITO_LOGOUT_URLS` | Comma-separated list of allowed logout URLs | No | `http://localhost:3000` |

## Sample .env File

Create a `.env` file in the root of your project with the following content:

```
# AWS Cognito Configuration
COGNITO_USER_POOL_ID=us-west-2_abcDEF123
COGNITO_CLIENT_ID=1abc2defghij3klmno4pqr5st
COGNITO_CLIENT_SECRET=your-client-secret-if-configured
AWS_REGION=us-west-2
COGNITO_DOMAIN=auth.yourapp.com

# Authentication Settings
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30
PASSWORD_MIN_LENGTH=8
MFA_ENABLED=false
EMAIL_VERIFICATION_REQUIRED=true

# Allowed URLs
COGNITO_CALLBACK_URLS=http://localhost:3000/callback,https://yourapp.com/callback
COGNITO_LOGOUT_URLS=http://localhost:3000,https://yourapp.com

# AWS Credentials (if not using IAM roles)
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_KEY
```

## Environment-Specific Settings

Different environments require different authentication configurations. Here are recommended settings for each environment:

### Development Environment

```
COGNITO_USER_POOL_ID=us-west-2_devUserPool
COGNITO_CLIENT_ID=dev-client-id
AWS_REGION=us-west-2
MFA_ENABLED=false
COGNITO_CALLBACK_URLS=http://localhost:3000/callback
COGNITO_LOGOUT_URLS=http://localhost:3000
```

### Staging Environment

```
COGNITO_USER_POOL_ID=us-west-2_stagingUserPool
COGNITO_CLIENT_ID=staging-client-id
AWS_REGION=us-west-2
MFA_ENABLED=true
COGNITO_CALLBACK_URLS=https://staging.yourapp.com/callback
COGNITO_LOGOUT_URLS=https://staging.yourapp.com
```

### Production Environment

```
COGNITO_USER_POOL_ID=us-west-2_prodUserPool
COGNITO_CLIENT_ID=prod-client-id
AWS_REGION=us-west-2
MFA_ENABLED=true
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
COGNITO_CALLBACK_URLS=https://yourapp.com/callback
COGNITO_LOGOUT_URLS=https://yourapp.com
```

## Troubleshooting Configuration Issues

### Common Issues and Solutions

| Issue | Possible Cause | Solution |
|-------|---------------|----------|
| "COGNITO_USER_POOL_ID or COGNITO_CLIENT_ID not set" | Environment variables not loaded | Ensure `.env` file exists and is being loaded by your application |
| "Invalid COGNITO_USER_POOL_ID" | Incorrect User Pool ID | Verify the User Pool ID in the AWS Cognito console |
| "Not authorized to access requested resource" | Incorrect AWS credentials or permissions | Check IAM permissions or AWS credentials |
| "Token issuer does not match" | Region mismatch | Ensure AWS_REGION matches the region of your User Pool |
| "Invalid client_id" | Incorrect Client ID | Verify the App Client ID in the AWS Cognito console |
| "CORS error during authentication" | Callback URL not authorized | Add the URL to COGNITO_CALLBACK_URLS and in the App Client settings |

### Debugging Environment Variables

1. **Verify environment variables are loaded:**

   Add debugging code to your application startup:

   ```python
   import os
   import logging

   logger = logging.getLogger(__name__)

   # Check essential Cognito variables
   cognito_user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
   cognito_client_id = os.getenv("COGNITO_CLIENT_ID")
   aws_region = os.getenv("AWS_REGION")

   logger.info(f"COGNITO_USER_POOL_ID: {'Set' if cognito_user_pool_id else 'NOT SET'}")
   logger.info(f"COGNITO_CLIENT_ID: {'Set' if cognito_client_id else 'NOT SET'}")
   logger.info(f"AWS_REGION: {aws_region}")
   ```

2. **Test AWS credentials:**

   Use AWS CLI to verify credentials:

   ```bash
   aws cognito-idp describe-user-pool --user-pool-id YOUR_USER_POOL_ID
   ```

3. **Check for typos:**
   
   Ensure there are no typos in variable names in your `.env` file or environment setup.

## Security Considerations for Environment Variables

### Protecting Sensitive Variables

1. **Never commit environment files to version control:**
   - Add `.env` to your `.gitignore` file
   - Use `.env.example` with placeholder values for documentation

2. **Use different credentials for each environment:**
   - Never share production credentials across environments
   - Create separate User Pools and App Clients for dev/staging/prod

3. **Restrict access to environment files:**
   - Limit who can access your `.env` files
   - Use secrets management services in production environments

4. **Environment variable encryption:**
   - Consider encrypting your `.env` files at rest
   - Tools like `git-crypt` can help if environment files need to be in version control

5. **CI/CD pipeline security:**
   - Use secret management systems in your CI/CD pipelines (e.g., GitHub Secrets, AWS Secrets Manager)
   - Never print environment variables in build logs

### Production Best Practices

1. **Use AWS Secrets Manager or AWS Parameter Store:**
   
   Instead of environment variables in production:

   ```python
   import boto3

   # Retrieve secrets from AWS Secrets Manager
   def get_secrets():
       client = boto3.client('secretsmanager')
       response = client.get_secret_value(SecretId='prod/experimentation-platform/cognito')
       return json.loads(response['SecretString'])
   ```

2. **Use IAM Roles instead of access keys:**
   - Configure EC2 instances, ECS tasks, or Lambda functions with IAM roles
   - Eliminates need to store AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY

3. **Regular credential rotation:**
   - Rotate App Client secrets regularly
   - Use temporary credentials whenever possible

4. **Audit environment variable access:**
   - Log access to sensitive configuration
   - Alert on unusual configuration access patterns

By following these guidelines, you'll ensure your Cognito authentication system is properly configured and secure across all environments.
