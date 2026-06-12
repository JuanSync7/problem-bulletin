/**
 * v2.29-S3 — Share page tests.
 *
 * Covers:
 *  1. Renders posts from the api (title, author label).
 *  2. Agent-authored post shows the bronze "agent" KindPill chip.
 *  3. Upvote click calls toggleVote and updates the count optimistically.
 *  4. "+ Share" form submits via createSharePost and prepends the post.
 *  5. Empty state renders with CTA.
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../../api/sharePosts";
import SharePage from "../index";

vi.mock("../../../api/sharePosts", () => ({
  listSharePosts: vi.fn(),
  createSharePost: vi.fn(),
  getSharePost: vi.fn(),
  toggleVote: vi.fn(),
}));

const listSharePosts = vi.mocked(api.listSharePosts);
const createSharePost = vi.mocked(api.createSharePost);
const toggleVote = vi.mocked(api.toggleVote);

function fakePost(overrides: Partial<api.SharePost> = {}): api.SharePost {
  return {
    id: "p-1",
    title: "How I triage with agents",
    body: "Some body text",
    tags: ["tips"],
    author_kind: "user",
    author_label: "Alice",
    ticket_id: null,
    ticket_display_id: null,
    agent_run_id: null,
    upvotes: 2,
    viewer_has_voted: false,
    created_at: new Date().toISOString(),
    updated_at: null,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter
      initialEntries={["/share"]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <SharePage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SharePage", () => {
  it("renders posts from the api", async () => {
    listSharePosts.mockResolvedValue({
      items: [
        fakePost(),
        fakePost({ id: "p-2", title: "Second post", author_label: "Bob" }),
      ],
      total: 2,
    });
    renderPage();
    expect(await screen.findByText("How I triage with agents")).toBeInTheDocument();
    expect(screen.getByText("Second post")).toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    // Both posts default to the "tips" tag, so the chip appears twice.
    expect(screen.getAllByText("#tips").length).toBe(2);
  });

  it("shows the agent chip for agent-authored posts", async () => {
    listSharePosts.mockResolvedValue({
      items: [
        fakePost({
          id: "p-agent",
          title: "Posted by a bot",
          author_kind: "agent",
          author_label: "ShareBot",
        }),
      ],
      total: 1,
    });
    renderPage();
    const card = (await screen.findByText("Posted by a bot")).closest(
      "[data-testid='share-card']",
    ) as HTMLElement;
    expect(within(card).getByText("agent")).toBeInTheDocument();
    expect(within(card).getByText("ShareBot")).toBeInTheDocument();
  });

  it("vote click calls api and updates count optimistically", async () => {
    listSharePosts.mockResolvedValue({
      items: [fakePost({ upvotes: 2, viewer_has_voted: false })],
      total: 1,
    });
    let resolveVote: (v: api.SharePostVoteResult) => void = () => {};
    toggleVote.mockImplementation(
      () =>
        new Promise<api.SharePostVoteResult>((res) => {
          resolveVote = res;
        }),
    );
    const user = userEvent.setup();
    renderPage();

    const voteBtn = await screen.findByRole("button", { name: "Upvote" });
    expect(voteBtn).toHaveTextContent("2");
    await user.click(voteBtn);

    // Optimistic bump before the api resolves.
    expect(toggleVote).toHaveBeenCalledWith("p-1");
    expect(
      screen.getByRole("button", { name: "Remove upvote" }),
    ).toHaveTextContent("3");

    // Server confirms.
    resolveVote({ voted: true, upvotes: 3 });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Remove upvote" }),
      ).toHaveTextContent("3"),
    );
  });

  it("create form submits and prepends the new post", async () => {
    listSharePosts.mockResolvedValue({ items: [fakePost()], total: 1 });
    createSharePost.mockResolvedValue(
      fakePost({ id: "p-new", title: "Brand new post", tags: ["fresh"] }),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("How I triage with agents");

    await user.click(screen.getByRole("button", { name: "+ Share" }));
    await user.type(screen.getByLabelText("Title"), "Brand new post");
    await user.type(screen.getByLabelText("Body"), "Body text here");
    await user.type(screen.getByLabelText("Tags"), "fresh, new");
    await user.click(screen.getByRole("button", { name: "Post" }));

    await waitFor(() =>
      expect(createSharePost).toHaveBeenCalledWith({
        title: "Brand new post",
        body: "Body text here",
        tags: ["fresh", "new"],
      }),
    );
    expect(await screen.findByText("Brand new post")).toBeInTheDocument();
    const cards = screen.getAllByTestId("share-card");
    expect(within(cards[0]).getByText("Brand new post")).toBeInTheDocument();
  });

  it("renders empty state with CTA when there are no posts", async () => {
    listSharePosts.mockResolvedValue({ items: [], total: 0 });
    renderPage();
    expect(await screen.findByText("Nothing shared yet")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Share something" }),
    ).toBeInTheDocument();
  });
});
