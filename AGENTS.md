# Development rules
- Preserve authorization in database queries before pagination and counting.
- Customer responses must never expose internal comments or internal audit events.
- Never log credentials or issue permanent access tokens.
- Add meaningful security regression tests for sensitive behavior and update SECURITY.md.
- Run Ruff, pytest against PostgreSQL, Bandit and pip-audit before reporting validation.
- Migrations are immutable once released. Do not use create_all in application startup.
- Include an English Conventional Commits suggestion in the final response.
