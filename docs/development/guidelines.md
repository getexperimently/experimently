# Experimently Development Guidelines

This document outlines the development standards, workflows, and best practices for the Experimently project. All team members should follow these guidelines to ensure code quality, maintainability, and consistency.

## Table of Contents

1. [Development Environment](#development-environment)
2. [Git Workflow](#git-workflow)
3. [Coding Standards](#coding-standards)
4. [Test-Driven Development](#test-driven-development)
5. [Code Review Process](#code-review-process)
6. [Documentation](#documentation)
7. [Continuous Integration](#continuous-integration)
8. [Security Guidelines](#security-guidelines)
9. [Performance Considerations](#performance-considerations)

## Development Environment

### Prerequisites

-   Python 3.11+
-   Node.js 16+
-   Docker and Docker Compose
-   AWS CLI v2
-   AWS CDK v2

### Local Setup

1. Clone the repository:

    ```bash
    git clone https://github.com/getexperimently/experimently.git
    cd experimently
    ```

2. Set up the backend:

    ```bash
    cd backend
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    pip install -r requirements.txt
    pre-commit install
    ```

3. Set up the frontend:

    ```bash
    cd frontend
    npm install
    ```

4. Start the local development environment:

    ```bash
    # From the project root
    docker-compose up -d
    ```

5. Run the backend server:

    ```bash
    # from the repository root
    python -m backend.app.db.bootstrap
    uvicorn backend.app.main:app --reload
    ```

6. Run the frontend development server:
    ```bash
    cd frontend
    npm run dev
    ```

### Environment Variables

Create a `.env` file in the backend directory with these variables:

```
# Development settings - NEVER use these in production
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/experimentation
REDIS_HOST=localhost
REDIS_PORT=6379
AWS_PROFILE=experimentation-dev
ENVIRONMENT=development
LOG_LEVEL=DEBUG
```

For local AWS services, you can use [localstack](https://github.com/localstack/localstack) which is included in the Docker Compose configuration.

## Git Workflow

We follow a Trunk-Based Development workflow with short-lived feature branches.

### Branch Naming

-   Feature branches: `feature/short-description`
-   Bug fixes: `fix/issue-reference-description`
-   Documentation: `docs/what-is-being-documented`
-   Infrastructure: `infra/what-is-being-changed`

### Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) standard:

```
feat: add user authentication middleware
^--^  ^--------------------------^
|     |
|     +-> Summary in present tense
|
+-------> Type: feat, fix, docs, style, refactor, test, chore
```

Common types:

-   `feat`: New feature
-   `fix`: Bug fix
-   `docs`: Documentation changes
-   `style`: Code style changes (formatting, etc.)
-   `refactor`: Code changes that neither fix bugs nor add features
-   `test`: Adding or modifying tests
-   `chore`: Changes to the build process, tooling, etc.

### Pull Requests

1. Create a new branch from `main`
2. Make your changes, committing regularly
3. Write or update tests for your changes
4. Ensure all tests pass locally
5. Push your branch and create a Pull Request
6. Fill out the PR template with all required information
7. Request review. `main` requires one approving review and, through
   `.github/CODEOWNERS`, the owner of every path the change touches
8. Address review feedback

PRs should be small and focused on a single issue or feature. Large changes should be broken down into smaller PRs.

## Coding Standards

### Python

-   Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guide
-   Format, sort imports and lint with [ruff](https://docs.astral.sh/ruff/)
    (line length 88, target `py311`). Ruff replaced black, isort and flake8:
    one tool, one config block (`[tool.ruff]` in `pyproject.toml`), the same
    version in CI, pre-commit and the venv. `.flake8` no longer exists; do not
    reintroduce black or isort.
-   `make format` runs the two fixing commands; `make lint` runs exactly what
    the `lint` CI job runs. Both scope ruff to `backend/ scripts/ modules/`
-   Use type hints for all function parameters and return values
-   Document functions and classes with docstrings (Google style)
-   Use meaningful variable and function names

### TypeScript/JavaScript

-   Follow the [Airbnb JavaScript Style Guide](https://github.com/airbnb/javascript)
-   Use TypeScript for all new code
-   Use functional components and hooks for React
-   Prefer named exports over default exports
-   Lint with ESLint (`frontend/eslint.config.mjs`, `--max-warnings 0`, over
    `frontend/src` and `modules/frontend/src`) and typecheck with `tsc
    --noEmit`. There is no Prettier in this repository

### Infrastructure as Code

-   Use AWS CDK for all infrastructure definitions
-   Document all resources with comments
-   Use environment variables for configurable values
-   Follow least-privilege principles for IAM roles

## Test-Driven Development

We follow test-driven development (TDD) practices:

1. Write tests first
2. Run the tests to ensure they fail (Red)
3. Write the minimum amount of code to make tests pass (Green)
4. Refactor the code while keeping tests passing (Refactor)

### Test Coverage Requirements

-   Backend code: minimum 80% coverage
-   Frontend components: minimum 70% coverage
-   Critical paths: 100% coverage required

### Testing Framework Standards

-   **Backend**: pytest with pytest-cov for coverage

    ```bash
    cd backend
    python -m pytest --cov=app
    ```

-   **Frontend**: Jest with React Testing Library

    ```bash
    cd frontend
    npm test
    ```

-   **Infrastructure**: AWS CDK assertions library
    ```bash
    cd infrastructure
    npm test
    ```

## Code Review Process

All code changes require review before merging:

1. **Automated Checks**: All PRs must pass CI checks (tests, linting, type checking)
2. **Peer Review**: At least one approval from a team member
3. **Maintainer Review**: Final approval from a project maintainer

### Review Checklist

Reviewers should check for:

-   Code correctness and quality
-   Test coverage and quality
-   Documentation
-   Performance implications
-   Security considerations
-   Adherence to coding standards

### Review Etiquette

-   Be respectful and constructive
-   Focus on the code, not the person
-   Provide specific, actionable feedback
-   Respond to reviews promptly
-   Use GitHub's suggestion feature for simple changes

## Documentation

Documentation is crucial for the project's success:

### Code Documentation

-   All public functions must have docstrings
-   Complex logic should be explained with comments
-   Update README and relevant docs when adding/changing features

### API Documentation

-   API endpoints are documented using OpenAPI/Swagger
-   The API docs are available at `/docs` when running the backend
-   Update API docs when changing endpoints

### Architecture Documentation

-   Keep architecture diagrams updated
-   Document design decisions and trade-offs
-   Update data flow diagrams when changing system behavior

## Continuous Integration

We use GitHub Actions for CI/CD:

-   **On Pull Request**: Run tests, linting, type checking
-   **On Merge to Main**: Deploy to development environment
-   **On Release**: Deploy to staging and production environments

### CI Checks

`main` requires these 20 checks. This list is what branch protection
actually enforces, not a description of what CI happens to run -- a pull
request cannot merge until every one reports success:

| | |
|---|---|
| `Unit Tests` | `integration-tests` |
| `Smoke Tests` | `Module Tests` |
| `Frontend Tests` | `Browser E2E` |
| `SDK Unit Tests` | `SDK Contract Tests` |
| `SDK Live Contract / sdk-live-contract (core)` | `CDK Stack Tests (Python)` |
| `core-build` | `full-build` |
| `Base Requirements Only` | `Docker Smoke` |
| `lint` | `regression-guard` |
| `Security Scan Summary` | `Release Gate Summary` |
| `Export Sweep` | `DCO` |

`lint` is the composite gate: ruff (format + lint), import-linter for the
core/modules boundary, `reuse lint` for licence headers, the requirements-lock
checks, eslint and `tsc --noEmit`, hadolint over the Dockerfiles, and
actionlint over the workflows. `make lint` runs the same thing locally.

Security scanning is Semgrep, Bandit, gitleaks, trufflehog and the container
and dependency scans, summarised by `Security Scan Summary`. `Leak Guard` runs
`scripts/leak_guard.py` on every push and pull request -- over the files AND
the commit messages -- so a secret or a false claim fails before it is
published rather than after. It is a required check, and pre-commit runs the
same script locally at both the `pre-commit` and `pre-push` stages.

Note there is no mypy in the gate. It is useful (`mypy backend/app/`) but it
is not wired into `make lint` or the `lint` job, so do not describe it as
enforced.

## Security Guidelines

Security is a priority for our platform:

-   No secrets in code or Git history
-   Use AWS Secrets Manager for sensitive configuration
-   Follow OWASP secure coding practices
-   Implement proper input validation
-   Use parameterized queries for database operations
-   Apply least privilege principle for all services
-   Regularly update dependencies

### Authentication & Authorization

-   Use Cognito for user authentication
-   Implement role-based access control
-   Always verify permissions before operations
-   Use JWT tokens with appropriate expiration
-   Implement proper token validation and refresh

## Performance Considerations

Performance is critical for experimentation platforms:

### Assignment Service

-   Must respond in < 50ms (p99)
-   Use caching aggressively
-   Implement consistent hashing for stability
-   Optimize database queries

### Event Collection

-   Design for high throughput (thousands/second)
-   Use batch processing where possible
-   Implement backpressure mechanisms
-   Monitor queue depths and latency

### General Guidelines

-   Profile code regularly
-   Set up performance benchmarks
-   Monitor database query performance
-   Use pagination for large result sets
-   Implement proper caching strategies
