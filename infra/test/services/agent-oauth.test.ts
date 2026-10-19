// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Template, Match } from "aws-cdk-lib/assertions";
import { IdpAuthenticationStack } from "../../lib/stacks/foundation";
import { McpStack } from "../../lib/stacks/services/mcp-stack";
import { ApiStack } from "../../lib/stacks/services/api-stack";
import { agentOauthCallbackUrls } from "../../lib/utils/agent-oauth";
import { DEFAULT_RESOURCE_PREFIX, DEFAULT_ENV } from "../../lib/constants";

jest.mock("../../lib/utils/python-bundling", () => ({
  bundlePython: () =>
    lambda.Code.fromInline("def handler(event, context): pass"),
}));

const CALLBACK =
  "https://bedrock-agentcore.us-east-1.amazonaws.com/identities/oauth2/callback/abc";
const BASE_CONTEXT = {
  resource_prefix: DEFAULT_RESOURCE_PREFIX,
  env: DEFAULT_ENV,
  context_manager_image_uri:
    "123456789012.dkr.ecr.us-east-1.amazonaws.com/coa-dev:latest",
  "aws:cdk:bundling-stacks": [],
};
const ENV = { account: "123456789012", region: "us-east-1" };

function authTemplate(extra: Record<string, unknown> = {}): Template {
  const app = new cdk.App({ context: { ...BASE_CONTEXT, ...extra } });
  return Template.fromStack(new IdpAuthenticationStack(app, "TestAuth"));
}

function mcpTemplate(extra: Record<string, unknown> = {}): Template {
  const app = new cdk.App({ context: { ...BASE_CONTEXT, ...extra } });
  const dep = new cdk.Stack(app, "Dep", { env: ENV });
  const vpc = new ec2.Vpc(dep, "Vpc", { maxAzs: 2 });
  const table = (id: string) =>
    new dynamodb.Table(dep, id, {
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
    });
  return Template.fromStack(
    new McpStack(app, "TestMcp", {
      env: ENV,
      vpc,
      rolesTable: table("Roles"),
      resourceRoleMappingsTable: table("RRM"),
    }),
  );
}

describe("agentOauthCallbackUrls", () => {
  const node = (v: unknown) =>
    new cdk.App({
      context: v === undefined ? {} : { agentOauthCallbackUrls: v },
    }).node;

  it("is off by default", () => {
    expect(agentOauthCallbackUrls(node(undefined))).toEqual([]);
  });

  it("accepts a single URL string or a JSON array", () => {
    expect(agentOauthCallbackUrls(node(CALLBACK))).toEqual([CALLBACK]);
    expect(agentOauthCallbackUrls(node(JSON.stringify([CALLBACK])))).toEqual([
      CALLBACK,
    ]);
  });

  it("accepts a comma-separated list (the deploy.sh form)", () => {
    const second = `${CALLBACK}-dev`;
    expect(agentOauthCallbackUrls(node(`${CALLBACK}, ${second}`))).toEqual([
      CALLBACK,
      second,
    ]);
    expect(agentOauthCallbackUrls(node(`${CALLBACK},`))).toEqual([CALLBACK]);
  });

  it("rejects non-HTTPS URLs", () => {
    expect(() => agentOauthCallbackUrls(node("http://example.com/cb"))).toThrow(
      /HTTPS/,
    );
    expect(() =>
      agentOauthCallbackUrls(node(`${CALLBACK},http://example.com/cb`)),
    ).toThrow(/HTTPS/);
  });
});

describe("agent OAuth disabled (default)", () => {
  it("auth stack creates no confidential client", () => {
    const t = authTemplate();
    t.resourcePropertiesCountIs(
      "AWS::Cognito::UserPoolClient",
      { GenerateSecret: true },
      0,
    );
    t.resourcePropertiesCountIs(
      "AWS::SSM::Parameter",
      { Name: `/${DEFAULT_RESOURCE_PREFIX}/agent-oauth-client-id` },
      0,
    );
  });

  it("MCP runtime keeps the allowedAudience authorizer", () => {
    mcpTemplate().hasResourceProperties("AWS::BedrockAgentCore::Runtime", {
      AuthorizerConfiguration: {
        CustomJWTAuthorizer: Match.objectLike({
          AllowedAudience: Match.anyValue(),
          CustomClaims: Match.absent(),
        }),
      },
    });
  });
});

function apiTemplate(extra: Record<string, unknown> = {}): Template {
  const app = new cdk.App({ context: { ...BASE_CONTEXT, ...extra } });
  const dep = new cdk.Stack(app, "Dep", { env: ENV });
  const vpc = new ec2.Vpc(dep, "Vpc", { maxAzs: 2 });
  // ApiStack attaches DynamoEventSources, which need streams.
  const table = (id: string) =>
    new dynamodb.Table(dep, id, {
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
    });
  return Template.fromStack(
    new ApiStack(app, "TestApi", {
      env: ENV,
      allowedOrigin: "*",
      vpc,
      rolesTable: table("Roles"),
      resourceRoleMappingsTable: table("RRM"),
      cacheInvalidationTable: table("Cache"),
    }),
  );
}

function authorizerClientId(t: Template): string {
  const fns = t.findResources("AWS::Lambda::Function", {
    Properties: { FunctionName: Match.stringLikeRegexp(".*authorizer$") },
  });
  return JSON.stringify(
    Object.values(fns)[0].Properties.Environment.Variables.CLIENT_ID,
  );
}

describe("REST authorizer client allowlist", () => {
  it("admits only the web client by default", () => {
    const clientId = authorizerClientId(apiTemplate());
    expect(clientId).toContain("userpoolclientid");
    expect(clientId).not.toContain("agentoauthclientid");
    expect(clientId).not.toContain("Fn::Join");
  });

  it("adds the agent client when agent OAuth is enabled", () => {
    const clientId = authorizerClientId(
      apiTemplate({ agentOauthCallbackUrls: CALLBACK }),
    );
    // Fn::Join of the two SSM parameter refs (logical ids drop the hyphens).
    expect(clientId).toContain("Fn::Join");
    expect(clientId).toContain("userpoolclientid");
    expect(clientId).toContain("agentoauthclientid");
  });
});

describe("agent OAuth enabled", () => {
  const ctx = { agentOauthCallbackUrls: CALLBACK };

  it("auth stack creates a confidential code-grant client with the callback", () => {
    authTemplate(ctx).hasResourceProperties("AWS::Cognito::UserPoolClient", {
      ClientName: `${DEFAULT_RESOURCE_PREFIX}-${DEFAULT_ENV}-agent-oauth-client`,
      GenerateSecret: true,
      AllowedOAuthFlows: ["code"],
      AllowedOAuthScopes: ["openid", "email", "profile"],
      CallbackURLs: [CALLBACK],
    });
  });

  it("auth stack publishes the client id to SSM", () => {
    authTemplate(ctx).hasResourceProperties("AWS::SSM::Parameter", {
      Name: `/${DEFAULT_RESOURCE_PREFIX}/agent-oauth-client-id`,
    });
  });

  it("MCP runtime pins the issuer instead of the audience", () => {
    mcpTemplate(ctx).hasResourceProperties("AWS::BedrockAgentCore::Runtime", {
      AuthorizerConfiguration: {
        CustomJWTAuthorizer: Match.objectLike({
          AllowedAudience: Match.absent(),
          AllowedClients: Match.absent(),
          CustomClaims: [
            Match.objectLike({
              InboundTokenClaimName: "iss",
              InboundTokenClaimValueType: "STRING",
            }),
          ],
        }),
      },
    });
  });

  it("MCP server allowlists both the MCP and agent clients", () => {
    const runtimes = mcpTemplate(ctx).findResources(
      "AWS::BedrockAgentCore::Runtime",
    );
    const env = Object.values(runtimes)[0].Properties.EnvironmentVariables;
    const joined = JSON.stringify(env.JWT_CLIENT_ID);
    // Fn::Join of the two SSM parameter refs (logical ids drop the hyphens).
    expect(joined).toContain("Fn::Join");
    expect(joined).toContain("mcpclientid");
    expect(joined).toContain("agentoauthclientid");
  });
});
