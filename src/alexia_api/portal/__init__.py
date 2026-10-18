"""The only code that knows how the portal works.

It owns the HTTP session, the allowlist of calls, login, the breaker, and one reader or writer
per portal feature. Everything it returns is a model from `alexia_api.domain`.
"""
