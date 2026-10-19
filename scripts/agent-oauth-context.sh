# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Sourced by deploy.sh and deploy-serve.sh. Appends the agent-platform OAuth
# (3LO) context to $CONTEXT, or refuses a deploy that would silently drop it.
#
# SCL_AGENT_OAUTH_CALLBACK_URLS: comma-separated callback URL(s), one per agent
# platform environment (see external-docs/content/agent-access.md). Once the
# client exists, EVERY later deploy of the auth, serve or MCP stack must pass the
# same list: without it the auth stack deletes the client, and the serve/MCP
# runtimes fall back to ID-token-only authorizers — either way every platform's
# stored user consents stop working.

if [ -n "${SCL_AGENT_OAUTH_CALLBACK_URLS:-}" ]; then
  # Comma-separated, never a JSON array: $CONTEXT is word-split unquoted, and an
  # unquoted "[...]" is a glob pattern.
  case "$SCL_AGENT_OAUTH_CALLBACK_URLS" in
    *[\[\]\ ]*)
      echo "ERROR: SCL_AGENT_OAUTH_CALLBACK_URLS must be comma-separated URLs (no brackets or spaces)" >&2
      exit 1
      ;;
  esac
  CONTEXT="$CONTEXT --context agentOauthCallbackUrls=$SCL_AGENT_OAUTH_CALLBACK_URLS"
else
  # The auth stack writes /<prefix>/agent-oauth-client-id only while the client
  # exists, so its presence means this deploy would drop agent OAuth.
  AGENT_OAUTH_PARAM="/${SCL_PREFIX:-coa}/agent-oauth-client-id"
  if [ "${SCL_REMOVE_AGENT_OAUTH:-}" != "1" ] \
    && aws ssm get-parameter --name "$AGENT_OAUTH_PARAM" >/dev/null 2>&1; then
    echo "ERROR: this deployment has an agent OAuth client ($AGENT_OAUTH_PARAM exists) but" >&2
    echo "       SCL_AGENT_OAUTH_CALLBACK_URLS is unset — deploying would turn agent OAuth off." >&2
    echo "       Set it to the current callback list (aws cognito-idp describe-user-pool-client" >&2
    echo "       ... --query UserPoolClient.CallbackURLs), or SCL_REMOVE_AGENT_OAUTH=1 to remove it." >&2
    exit 1
  fi
fi
