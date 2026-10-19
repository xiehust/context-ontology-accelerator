# Agent Access Guide

Context Ontology Accelerator supports programmatic access from AI agents and
automation tools. Agents **always act on behalf of a user** using the same
OIDC three-legged (3LO) auth flow as the web app — there are no separate
machine-to-machine credentials. An agent carries the user's delegated token,
and every request is authorized against that user's grants.

## Overview

There are two ways agents connect, both under the same delegated-auth model:

- **MCP (Model Context Protocol)** — the primary path for AI agents (Claude,
  Amazon Q, IDE integrations like Kiro/Claude Desktop/Cursor). Ontology
  Accelerator runs an MCP server on AgentCore Runtime exposing 6 tools —
  `list_metrics` and `describe_schema` for discovery, plus `query`,
  `translate_sparql`, `rag_retrieval`, and `graph_traversal` for execution.
  See "MCP Server Setup" below.
- **Direct REST API** — for scripts, notebooks, or custom automation that
  isn't going through an MCP client. Uses the same endpoints the web app
  calls; see "Making API Calls" below.

Either way, an agent needs:

1. A valid OIDC token obtained on behalf of a user via the 3LO Authorization
   Code flow (with PKCE)
2. The acting user to have the necessary grants in the system (User- or
   Group-based, same as any human user)

The agent never has its own standalone identity or permissions — it inherits
exactly what the user it represents is allowed to do.

!!! tip "Full request/response schemas"
    For MCP tool schemas, connect an MCP client and let it introspect the
    server. For the direct REST API, see the
    **[API Reference](#/api-reference)** — Control Plane API for grants,
    metrics, sources, etc., and Data Layer (Serve) API for `Query` and the
    other runtime operations. This guide covers authentication and grant
    setup specific to agents; those references are the source of truth for
    schemas.

## MCP Server Setup

The MCP server runs on AgentCore Runtime, reachable over **Streamable HTTP**.
Configure your MCP client (Claude Desktop, Kiro, Cursor, etc.) with:

- The MCP server's AgentCore Runtime endpoint (from the `coa-dev-mcp` stack outputs)
- The user's Bearer token, obtained via the same OIDC 3LO + PKCE flow described below

For the MCP/CLI flow specifically, the platform provisions a dedicated public
client with a `localhost:9876/oauth/callback` redirect URI (see the
[Authentication Setup Guide](authentication-setup.md)) so IDE integrations can
complete the PKCE login without a server-side secret.

Each tool call is authorized exactly like a REST call: the server extracts
the Bearer token from the request, forwards it to the same authorizer path,
and the acting user's grants determine what the tool can do — a `data-analyst`
grant restricted to certain tables via `tableAllowlist` restricts `query` tool
calls the same way it would restrict a direct API call.

## Agent platforms with a token vault (3LO through AgentCore Gateway)

Agent platforms that broker per-user OAuth themselves — for example an
AgentCore Gateway MCP-server target whose credential is an AgentCore Identity
OAuth2 provider in "act as user" (Authorization Code) mode — need a
**confidential** client, and they present the user's Cognito **access** token
rather than an ID token. Neither works with the default deployment: the web
and MCP clients are public (no secret), and the Serve/MCP runtimes only admit
ID tokens (`allowedAudience`).

Enable it per deployment with the `agentOauthCallbackUrls` context: the
platform's OAuth callback URL(s), one per agent platform environment, as a
single URL, a comma-separated list or a JSON array. Through the deploy scripts,
set `SCL_AGENT_OAUTH_CALLBACK_URLS` (comma-separated):

```bash
SCL_AGENT_OAUTH_CALLBACK_URLS=https://bedrock-agentcore.<region>.amazonaws.com/identities/oauth2/callback/<id> \
  make deploy-dev
```

Pass the **same** list on every later deploy of the `auth`, `serve` and `mcp`
stacks. Without it the auth stack deletes the client and the runtimes fall
back to ID tokens only, so every user consent the platform stored stops
working. `scripts/deploy.sh` and `scripts/deploy-serve.sh` therefore refuse to
run while the client exists and the variable is unset (set
`SCL_REMOVE_AGENT_OAUTH=1` to remove it on purpose). A hand-run `cdk deploy`
must pass the context itself:

```bash
cdk deploy <prefix>-<env>-auth <prefix>-<env>-serve <prefix>-<env>-mcp <prefix>-<env>-api -e \
  --context agentOauthCallbackUrls=https://bedrock-agentcore.<region>.amazonaws.com/identities/oauth2/callback/<id>
```

This:

- creates the `<prefix>-<env>-agent-oauth-client` app client (code grant,
  `openid email profile`, client secret) and publishes its id to SSM
  `/<prefix>/agent-oauth-client-id` (read the secret with
  `aws cognito-idp describe-user-pool-client`);
- switches both runtime authorizers from `allowedAudience` to an issuer-only
  rule (`iss` = the user pool). AgentCore ANDs all configured checks and
  `allowedClients` rejects ID tokens, so no client/audience combination admits
  both token kinds. The client boundary moves into the MCP server, whose
  independent check (`JWT_CLIENT_ID`) becomes the allowlist
  `<mcp client>,<agent client>`, matched against `aud` or `client_id`;
- adds the agent client to the REST API authorizer (`CLIENT_ID` becomes
  `<web client>,<agent client>`), so the platform can also call the Control
  Plane and Data Layer REST APIs with the same access token — for example a
  console that lists the namespaces, sources and metrics the user may see.

Register the confidential client in the platform (client id, secret, discovery
URL `https://cognito-idp.<region>.amazonaws.com/<pool>/.well-known/openid-configuration`,
scopes `openid email profile`) and point the platform at the MCP runtime's
invocations URL (a gateway target, or an MCP tool that sends the user's token).

**Example — AgentCore Launchpad.** Each Launchpad environment registers the
agent client once as an OAuth2 Connection (an AgentCore Identity credential
provider), whose callback URL goes into `SCL_AGENT_OAUTH_CALLBACK_URLS`. One
consent per user, held by Launchpad's console workload identity, serves its
COA console module (REST + Serve streaming) and its managed-Harness agents
(the user's token is sent to the MCP runtime as `Authorization: Bearer`);
Strands agents obtain their own per-agent consent through the same Connection.

!!! warning "Access tokens carry no email"
    Cognito access tokens have `sub` and `cognito:groups` but no `email`, so a
    caller on this path matches grants made to `User::<sub>` or to one of its
    groups, not grants made to its email address.

## Obtaining a Token (3LO, on behalf of a user)

Agents obtain tokens through the standard Authorization Code flow with PKCE,
the same flow the web app uses. The user authenticates once (interactively),
and the agent uses the resulting tokens to call the API on their behalf.

1. The user completes the OIDC Authorization Code + PKCE login, authorizing the
   agent.
2. The agent exchanges the authorization code for an ID token, access token,
   and refresh token.
3. The agent calls the API with the user's bearer token, refreshing it with the
   refresh token as needed.

```bash
# Example: exchange an authorization code obtained via the 3LO flow
TOKEN=$(curl -s -X POST "https://your-domain.auth.us-east-1.amazoncognito.com/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code&client_id=CLIENT_ID&code=AUTH_CODE&redirect_uri=REDIRECT_URI&code_verifier=PKCE_VERIFIER" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id_token'])")
```

When the token nears expiry, refresh it instead of re-prompting the user:

```bash
TOKEN=$(curl -s -X POST "https://your-domain.auth.us-east-1.amazoncognito.com/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=refresh_token&client_id=CLIENT_ID&refresh_token=REFRESH_TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id_token'])")
```

## Granting Access

Because an agent acts on behalf of a user, you do **not** grant access to the
agent itself — you grant access to the user (or an IdP group the user belongs
to), via `POST /namespaces/{namespaceId}/grants` — see **CreateGrant** in the
[API Reference](#/api-reference) and the
[Role & Permission Management Guide](role-permission-management.md) for
assigning roles.

For restricted access (the user — and therefore the agent — can only query
specific tables), add `tableAllowlist` / `allowedMetrics` to the same grant
request.

## Making API Calls (Direct REST, without MCP)

For agents or scripts not using an MCP client, call the REST API directly
with the user's bearer token — see the [API Reference](#/api-reference) for
every available endpoint (metrics, sources, ontologies, grants under the
Control Plane API; `Query` and the other runtime operations under the Data
Layer API).

## Auditing Agent Actions

All agent calls — MCP tool invocations and direct REST calls alike — pass
through the same authorizer as direct human access. Because the agent acts
on behalf of a user, the audited `principalId` is the acting user's identity.
The authorizer logs every decision with:

- `principalId` — the acting user's identity
- `effect` — Allow/Deny
- `globalRoles` / resource roles

Query CloudWatch Logs Insights:

```
fields @timestamp, principalId, effect, resource
| filter principalId = "alice@company.com"
| sort @timestamp desc
| limit 50
```

For data-level access auditing (which tables/columns were queried), check the
context-manager logs which record SQL Firewall decisions.

## Best Practices

| Practice | Rationale |
|----------|-----------|
| Scope grants to the acting user | The agent inherits exactly the user's permissions — keep them least-privilege |
| Apply `tableAllowlist` on grants | Agents rarely need every table the user can otherwise reach |
| Refresh tokens instead of re-prompting | Use the refresh token for long-running workflows |
| Monitor DLQs and error rates | Agent failures are silent without monitoring |
| Grant to Groups when possible | Manage access via IdP group membership |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401` on API call | Token expired or malformed | Refresh the user's token; verify the issuer/`authority` |
| `403` on API call | The acting user has no grant | Create a grant for the user's principal ID |
| Token expires mid-workflow | No refresh handling | Use the refresh token to renew the user's token |
| Agent can authenticate but queries return empty | Data-level restrictions too narrow | Check `tableAllowlist` and `allowedMetrics` on the user's grant |
