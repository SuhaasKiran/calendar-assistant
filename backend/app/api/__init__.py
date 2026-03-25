"""
HTTP API layer: route modules grouped by concern (auth, chat, health).

Routers stay thin: validate input, call services/agent, return responses or streaming bodies.
"""
