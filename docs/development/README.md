# Development Documentation

This directory contains development guidelines, best practices, and technical documentation for Experimently.

## Files

1. [Development Guidelines](guidelines.md)
   - Coding standards
   - Git workflow
   - Code review process
   - Testing requirements
   - Documentation requirements

2. **Database**
   - [Migrations Guide](database/migrations.md)
     - Creating migrations
     - Running migrations
     - Rollback procedures
   - [Usage Guide](database/usage.md)
     - Query optimization
     - Connection management
     - Transaction handling
   - [Backup Guide](database/backup.md)
     - Backup procedures
     - Retention policies
     - Recovery processes

3. [Dependency Injection](dependency-injection.md)
   - DI patterns
   - Service registration
   - Lifecycle management
   - Best practices

4. [Workflow Guide](workflow-explanation.md)
   - Development workflow
   - CI/CD pipeline
   - Deployment process
   - Release management

   - Project roadmap
   - Sprint planning
   - Feature prioritization
   - Technical debt management

## Common Tasks

1. **Database Management**
   - [Creating Migrations](database/migrations.md#creating-new-migrations)
   - [Running Backups](database/backup.md#backup-mechanism)
   - [Query Optimization](database/usage.md#performance-optimization)

2. **Development Process**
   - [Git Workflow](guidelines.md#git-workflow)
   - [Code Reviews](guidelines.md#code-review-process)
   - [Testing](guidelines.md)

3. **Deployment**
   - [CI/CD Pipeline](workflow-explanation.md)
   - [Release Process](workflow-explanation.md)
   - [Environment Management](workflow-explanation.md)

4. **Deterministic Backend Test Profile**
   - Start test dependencies with Docker Compose:
     - `docker compose -f docker-compose.test.yml up -d postgres-test redis-test`
   - Run the standardized backend release checks:
     - `./scripts/run-backend-tests.sh release`
   - For full local parity (starts/stops containers automatically):
     - `EP_TEST_PROFILE=compose ./scripts/run-backend-tests.sh all`

## Best Practices

1. **Code Quality**
   - Follow the [coding standards](guidelines.md#coding-standards)
   - Write comprehensive tests
   - Document your code
   - Review before committing

2. **Database**
   - Use migrations for schema changes
   - Follow backup procedures
   - Optimize queries
   - Handle transactions properly

3. **Architecture**
   - Use dependency injection
   - Follow SOLID principles
   - Write modular code
   - Consider scalability

## Need Help?

- Review the [Development Guidelines](guidelines.md)
- Check the [Database Guides](database/)
- See the [Workflow Documentation](workflow-explanation.md)
- Contact the development team for assistance
