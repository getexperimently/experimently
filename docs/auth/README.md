# Authentication Documentation

This directory contains documentation related to authentication and authorization in Experimently.

## Files

1. [Environment Setup](auth-environment-variables.md)
   - Environment variables configuration
   - AWS Cognito setup
   - Local development settings
   - Production configuration

2. [Authentication Flow](flow.md)
   - Sign-up and login flows
   - Token management
   - Session handling
   - Password reset process
   - Flow diagrams

3. [User Guide](auth-user-guide.md)
   - User registration
   - Account management
   - Password policies
   - MFA setup
   - Role management

4. [Developer Guide](auth-developer-docs.md)
   - Implementation details
   - Security best practices
   - Integration examples
   - Testing guidelines
   - Troubleshooting

5. [Testing Guide](cognito-auth-testing.md)
   - Unit testing
   - Integration testing
   - E2E testing
   - Mock configurations
   - Test data setup

6. [SSO (SAML 2.0 / OIDC, the `sso` module)](sso.md)
   - SAML 2.0 setup (Okta, Azure AD, OneLogin, Auth0)
   - OIDC setup (Google Workspace, GitHub, Microsoft, Auth0)
   - JIT user provisioning
   - Group-to-role mapping
   - Enforced SSO configuration
   - Environment variables reference

## Common Tasks

1. **User Management**
   - [Creating Users](auth-user-guide.md)
   - [Managing Roles](auth-user-guide.md)
   - [Password Reset](auth-user-guide.md#password-reset-process)

2. **Development**
   - [Local Setup](auth-environment-variables.md)
   - [Testing](cognito-auth-testing.md)
   - [Integration](auth-developer-docs.md#frontend-login-integration)

3. **Security**
   - [Best Practices](auth-developer-docs.md)
   - [Token Management](flow.md)
   - [MFA Setup](auth-user-guide.md)

4. **SSO (the `sso` module)**
   - [Okta SAML Setup](sso.md#okta-saml-20)
   - [Azure AD (SAML) Setup](sso.md#azure-active-directory-saml)
   - [Google OIDC Setup](sso.md#google-workspace-oidc)
   - [GitHub OIDC Setup](sso.md#github-oidc)
   - [Okta OIDC Setup](sso.md#okta-oidc)
   - [Role Mapping](sso.md#group-to-role-mapping)

## Need Help?

- Review the [Developer Guide](auth-developer-docs.md) for implementation details
- Check the [User Guide](auth-user-guide.md) for user management
- See the [Flow Documentation](flow.md) for process understanding
- Contact the security team for additional assistance
