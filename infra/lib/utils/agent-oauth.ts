// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore";
import { Node } from "constructs";
import { CTX_AGENT_OAUTH_CALLBACK_URLS } from "../constants";

/** SSM parameter (under ssmPrefix) holding the agent OAuth client id. */
export const AGENT_OAUTH_CLIENT_ID_PARAM = "agent-oauth-client-id";

/**
 * Callback URLs configured for the opt-in agent OAuth client, or `[]` when
 * the feature is off. Accepts a JSON array, a single URL, or a
 * comma-separated list (`-c agentOauthCallbackUrls=https://a,https://b` —
 * the form scripts/deploy.sh passes from SCL_AGENT_OAUTH_CALLBACK_URLS, since
 * an unquoted JSON array would be glob-expanded by the shell).
 */
export function agentOauthCallbackUrls(node: Node): string[] {
  const raw = node.tryGetContext(CTX_AGENT_OAUTH_CALLBACK_URLS) as
    | string
    | string[]
    | undefined;
  if (raw === undefined || raw === null || raw === "") return [];
  let urls: unknown = raw;
  if (typeof raw === "string") {
    const trimmed = raw.trim();
    urls = trimmed.startsWith("[")
      ? JSON.parse(trimmed)
      : trimmed
          .split(",")
          .map((u) => u.trim())
          .filter((u) => u.length > 0);
  }
  if (
    !Array.isArray(urls) ||
    !urls.length ||
    !urls.every((u) => typeof u === "string" && /^https:\/\/.+/.test(u))
  ) {
    throw new Error(
      `${CTX_AGENT_OAUTH_CALLBACK_URLS} must be an HTTPS URL or a non-empty JSON array of HTTPS URLs`,
    );
  }
  return urls as string[];
}

export function agentOauthEnabled(node: Node): boolean {
  return agentOauthCallbackUrls(node).length > 0;
}

/**
 * Inbound JWT authorizer for the Serve/MCP runtimes.
 *
 * Default: `allowedAudience` = the web and MCP clients. Only ID tokens carry
 * `aud`, so this accepts exactly the ID tokens those two clients issue.
 *
 * With agent OAuth enabled, the agent platform presents the user's Cognito
 * ACCESS token (no `aud`, `client_id` = agent client). AgentCore ANDs every
 * configured check and `allowedClients` rejects ID tokens (they lack
 * `client_id`), so no client/audience combination admits both token kinds.
 * The authorizer then pins the issuer only (signature + expiry + `iss`), and
 * the client allowlist is enforced in application code (MCP server
 * `JWT_CLIENT_ID`, which matches `aud` OR `client_id`). Every client in the
 * pool is provisioned by this app, so the platform-level boundary stays the
 * deployment's own user pool.
 */
export function runtimeJwtAuthorizer(
  node: Node,
  issuerUrl: string,
  audiences: string[],
): bedrockagentcore.RuntimeAuthorizerConfiguration {
  const discoveryUrl = `${issuerUrl}/.well-known/openid-configuration`;
  if (agentOauthEnabled(node)) {
    return bedrockagentcore.RuntimeAuthorizerConfiguration.usingJWT(
      discoveryUrl,
      undefined,
      undefined,
      undefined,
      [bedrockagentcore.RuntimeCustomClaim.withStringValue("iss", issuerUrl)],
    );
  }
  return bedrockagentcore.RuntimeAuthorizerConfiguration.usingJWT(
    discoveryUrl,
    undefined,
    audiences,
  );
}
