"""What a server needs and the portal layer does not.

It holds the per-account caches, the child directory, API keys, and rate limits. It imports from
`alexia_api.portal` and `alexia_api.domain`, and nothing in `alexia_api.api`.
"""
