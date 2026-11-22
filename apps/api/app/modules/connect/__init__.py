"""Connect: customers plug their Stravica Social account into AI assistants (Claude, ChatGPT, any MCP client) and
automation tools, without copying keys.

* ``oauth.py``  — our own OAuth 2.1 authorization server (PKCE S256, dynamic client registration RFC 7591, client ID
  metadata documents, RFC 8414 / RFC 9728 metadata, resource indicators RFC 8707, issuer in responses RFC 9207).
  Separate from the social-network OAuth at ``/oauth/callback``.
* ``keys.py``   — personal API keys (``sk_stravica_…``) for developers (Zapier, n8n…); same bearer layer.
* ``mcp.py``    — the remote MCP server at ``/mcp`` (Streamable HTTP, stateless, official ``mcp`` SDK).
* ``tools.py``  — the tools: each runs as the token's user, in the token's workspace, with that user's role, the
  plan (feature ``mcp``) and the token's scopes enforced; writes are recorded in ``connect_audit``.

The assistant does the thinking and writing with the user's own subscription; the tools give data and act.
"""
