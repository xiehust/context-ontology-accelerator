// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { vi, describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import createWrapper from "@cloudscape-design/components/test-utils/dom";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import React from "react";
import { Playground } from "../../../src/pages/Playground";

// Shared across both hook mocks below so a test can assert on what the page sent.
const STRATEGY_SELECT = '[data-testid="strategy-select"]';
const { sendQueryMock } = vi.hoisted(() => ({ sendQueryMock: vi.fn() }));

vi.mock("../../../src/components/RuntimeContext", () => ({
  RuntimeConfigContext: React.createContext({
    region: "us-east-1",
    serveRuntimeArn:
      "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test",
    oidcConfig: { authority: "https://mock", clientId: "c" },
  }),
}));

vi.mock("../../../src/components/NamespaceProvider", () => ({
  useCurrentNamespace: () => ({
    namespaceId: "ns-1",
    current: { namespaceId: "ns-1", name: "test", displayName: "Test" },
    namespaces: [],
    setNamespace: vi.fn(),
    isLoading: false,
  }),
}));

vi.mock("../../../src/api-hooks", () => ({
  usePlaygroundChatSSE: () => ({
    state: { messages: [] },
    sessionId: null,
    isRestoring: false,
    isStreaming: false,
    sendQuery: sendQueryMock,
    newChat: vi.fn(),
    retryQuery: vi.fn(),
    hasMoreHistory: false,
    isLoadingOlderHistory: false,
    requestOlderHistory: vi.fn(),
  }),
}));

vi.mock("../../../src/api-hooks/use-playground-chat-sse", () => ({
  usePlaygroundChatSSE: () => ({
    state: { messages: [] },
    sessionId: null,
    isRestoring: false,
    isStreaming: false,
    sendQuery: sendQueryMock,
    newChat: vi.fn(),
    retryQuery: vi.fn(),
    hasMoreHistory: false,
    isLoadingOlderHistory: false,
    requestOlderHistory: vi.fn(),
  }),
}));

vi.mock("../../../src/components/SplitPanelProvider", () => ({
  useSplitPanel: () => ({
    state: { content: null, isOpen: false, header: "" },
    openPanel: vi.fn(),
    closePanel: vi.fn(),
  }),
}));

vi.mock("../../../src/components/ToolsPanelProvider", () => ({
  useToolsPanel: () => ({
    state: { drawers: [], activeDrawerId: null },
    registerDrawer: vi.fn(),
    unregisterDrawer: vi.fn(),
    openDrawer: vi.fn(),
    closeDrawer: vi.fn(),
    toggleDrawer: vi.fn(),
  }),
}));

function renderPlayground() {
  return render(
    <MemoryRouter initialEntries={["/playground"]}>
      <Routes>
        <Route path="/playground" element={<Playground />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Playground", () => {
  it("renders the playground header", () => {
    renderPlayground();
    expect(
      screen.getByText("Playground"),
    ).toBeInTheDocument();
  });

  it("renders the chat container with empty state", () => {
    renderPlayground();
    expect(
      screen.getByText("Ask a question against the governed surface..."),
    ).toBeInTheDocument();
  });

  it("sends the selected strategy with the query", () => {
    sendQueryMock.mockClear();
    const { container } = renderPlayground();
    const select = createWrapper(container).findSelect(STRATEGY_SELECT)!;
    select.openDropdown();
    select.selectOptionByValue("ontop_first");

    const input = screen.getByRole("textbox", { name: "Query" });
    fireEvent.change(input, { target: { value: "how many orders?" } });
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));

    expect(sendQueryMock).toHaveBeenCalledWith(
      "how many orders?",
      "standard",
      "ontop_first",
    );
  });

  it("defaults the strategy to nl_to_sql_first", () => {
    const { container } = renderPlayground();
    expect(
      createWrapper(container).findSelect(STRATEGY_SELECT)!.getElement(),
    ).toHaveTextContent("nl_to_sql_first");
  });
});
