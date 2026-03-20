import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { stripExifFromFile, stripExifFromFiles } from "./stripExif";

describe("stripExifFromFile", () => {
  it("returns GIF files unchanged", async () => {
    const file = new File(["gif content"], "test.gif", { type: "image/gif" });
    const result = await stripExifFromFile(file);
    expect(result).toBe(file);
  });

  it("returns WebP files unchanged", async () => {
    const file = new File(["webp content"], "test.webp", { type: "image/webp" });
    const result = await stripExifFromFile(file);
    expect(result).toBe(file);
  });

  it("returns non-image files unchanged", async () => {
    const file = new File(["text content"], "test.txt", { type: "text/plain" });
    const result = await stripExifFromFile(file);
    expect(result).toBe(file);
  });

  it("returns PDF files unchanged", async () => {
    const file = new File(["pdf content"], "test.pdf", { type: "application/pdf" });
    const result = await stripExifFromFile(file);
    expect(result).toBe(file);
  });

  it("processes JPEG files via canvas re-encoding", async () => {
    const mockBlob = new Blob(["stripped"], { type: "image/jpeg" });
    const mockCtx = { drawImage: vi.fn() };
    const mockCanvas = {
      width: 0,
      height: 0,
      getContext: vi.fn(() => mockCtx),
      toBlob: vi.fn((cb: (b: Blob) => void) => cb(mockBlob)),
    };

    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      if (tag === "canvas") return mockCanvas as any;
      return origCreateElement(tag);
    });

    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();

    // Mock Image as a constructor class
    const origImage = globalThis.Image;
    class MockImage {
      naturalWidth = 100;
      naturalHeight = 100;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      _src = "";
      get src() { return this._src; }
      set src(v: string) {
        this._src = v;
        setTimeout(() => this.onload?.(), 0);
      }
    }
    globalThis.Image = MockImage as any;

    const file = new File(["jpeg data"], "photo.jpg", { type: "image/jpeg" });
    const result = await stripExifFromFile(file);

    expect(result).not.toBe(file);
    expect(result.name).toBe("photo.jpg");
    expect(result.type).toBe("image/jpeg");
    expect(mockCtx.drawImage).toHaveBeenCalled();

    vi.restoreAllMocks();
    globalThis.Image = origImage;
  });

  it("processes PNG files via canvas re-encoding", async () => {
    const mockBlob = new Blob(["stripped"], { type: "image/png" });
    const mockCtx = { drawImage: vi.fn() };
    const mockCanvas = {
      width: 0,
      height: 0,
      getContext: vi.fn(() => mockCtx),
      toBlob: vi.fn((cb: (b: Blob) => void) => cb(mockBlob)),
    };

    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      if (tag === "canvas") return mockCanvas as any;
      return origCreateElement(tag);
    });

    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();

    const origImage = globalThis.Image;
    class MockImage {
      naturalWidth = 200;
      naturalHeight = 150;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      _src = "";
      get src() { return this._src; }
      set src(v: string) {
        this._src = v;
        setTimeout(() => this.onload?.(), 0);
      }
    }
    globalThis.Image = MockImage as any;

    const file = new File(["png data"], "image.png", { type: "image/png" });
    const result = await stripExifFromFile(file);

    expect(result).not.toBe(file);
    expect(result.name).toBe("image.png");
    expect(result.type).toBe("image/png");

    vi.restoreAllMocks();
    globalThis.Image = origImage;
  });

  it("returns original file if canvas context unavailable", async () => {
    const mockCanvas = {
      width: 0,
      height: 0,
      getContext: vi.fn(() => null),
    };

    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      if (tag === "canvas") return mockCanvas as any;
      return origCreateElement(tag);
    });

    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();

    const origImage = globalThis.Image;
    class MockImage {
      naturalWidth = 100;
      naturalHeight = 100;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      _src = "";
      get src() { return this._src; }
      set src(v: string) {
        this._src = v;
        setTimeout(() => this.onload?.(), 0);
      }
    }
    globalThis.Image = MockImage as any;

    const file = new File(["jpeg data"], "photo.jpg", { type: "image/jpeg" });
    const result = await stripExifFromFile(file);

    expect(result).toBe(file);

    vi.restoreAllMocks();
    globalThis.Image = origImage;
  });
});

describe("stripExifFromFiles", () => {
  it("processes multiple files", async () => {
    const gif = new File(["gif"], "a.gif", { type: "image/gif" });
    const txt = new File(["text"], "b.txt", { type: "text/plain" });
    const results = await stripExifFromFiles([gif, txt]);
    expect(results.length).toBe(2);
    expect(results[0]).toBe(gif);
    expect(results[1]).toBe(txt);
  });

  it("handles empty array", async () => {
    const results = await stripExifFromFiles([]);
    expect(results).toEqual([]);
  });
});
