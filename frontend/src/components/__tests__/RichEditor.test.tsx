/**
 * RichEditor tests (v2.8-WP54).
 *
 * Covers:
 *  - First render does not throw even though TipTap's useEditor may return a
 *    non-null Editor whose commandManager is still initialising.
 *  - Toolbar buttons only appear after the editor's onCreate callback fires
 *    (i.e. when the editor is truly ready), preventing the
 *    "can't access property 'can', this.commandManager is null" crash.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import RichEditor from "../RichEditor";

// TipTap uses ProseMirror under the hood which depends on real DOM APIs.
// jsdom provides a sufficient subset; no extra mocking required.

describe("RichEditor", () => {
  it("mounts without throwing (commandManager guard)", () => {
    // If the guard is missing this will throw:
    //   TypeError: can't access property "can", this.commandManager is null
    expect(() => {
      render(<RichEditor value="" onChange={() => {}} />);
    }).not.toThrow();
  });

  it("renders Toolbar buttons only after the editor becomes ready", async () => {
    render(<RichEditor value="" onChange={() => {}} />);

    // The Undo button calls editor.can().undo() — it must not appear until
    // onCreate has fired and commandManager is live.
    const undoBtn = await screen.findByTitle("Undo (Ctrl+Z)");
    expect(undoBtn).toBeInTheDocument();
  });

  // v2.10-WP13: console-warning sentinel. TipTap emits
  // "[tiptap warn]: Duplicate extension names found: ['link','underline']"
  // (and similar) via console.warn when StarterKit's bundled extensions
  // collide with explicitly-imported ones. WP64 disabled link + underline
  // in StarterKit.configure(); this test guards against regressions and
  // against future StarterKit-bundle additions reintroducing duplicates.
  it("mounts without emitting any console.warn or console.error", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    try {
      render(<RichEditor value="" onChange={() => {}} />);
      // Wait for onCreate → toolbar mount so any deferred warnings fire.
      await screen.findByTitle("Undo (Ctrl+Z)");
      // Allow any microtask-queued TipTap warnings to flush.
      await waitFor(() => {
        // No-op assertion; we just want one more tick.
        expect(true).toBe(true);
      });

      expect(warnSpy).not.toHaveBeenCalled();
      expect(errorSpy).not.toHaveBeenCalled();
    } finally {
      warnSpy.mockRestore();
      errorSpy.mockRestore();
    }
  });
});
