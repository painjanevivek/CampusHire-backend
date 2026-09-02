"""Keep the backend test process isolated from local development services."""

import os

# A developer may enable seeded demo accounts and run Redis locally. Neither
# should change test outcomes or leak rate-limit state between test runs.
os.environ["DEMO_LOGIN_ENABLED"] = "false"
os.environ["DEMO_ADMIN_MFA_BYPASS"] = "false"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"
