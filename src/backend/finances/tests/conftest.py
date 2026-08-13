# `user`, `other_user`, `household`, `other_household` and `logged_client` all
# live in the root `src/backend/conftest.py` — one definition, reachable from
# every app's tests. Do not shadow `logged_client` here: a copy that omits the
# `household` dependency makes household-scoped view tests pass vacuously.
