import { createSignal, For, Show } from "solid-js";
import { useI18n } from "@nekonoverse/ui/i18n";
import {
  theme,
  setTheme,
  customColors,
  setCustomColors,
  customThemeName,
  setCustomThemeName,
  clearCustomColors,
  PRESET_COLORS,
  COLOR_KEYS,
  type Theme,
  type ThemeColors,
  type ThemeCustomization,
} from "@nekonoverse/ui/stores/theme";
import { updateThemeCustomization } from "@nekonoverse/ui/api/settings";

interface ColorGroup {
  labelKey: string;
  keys: (keyof ThemeColors)[];
}

const COLOR_GROUPS: ColorGroup[] = [
  {
    labelKey: "themeCustomizer.categoryBackground",
    keys: ["bg-primary", "bg-secondary", "bg-card"],
  },
  {
    labelKey: "themeCustomizer.categoryText",
    keys: ["text-primary", "text-secondary"],
  },
  {
    labelKey: "themeCustomizer.categoryAccent",
    keys: ["accent", "accent-hover", "accent-text"],
  },
  {
    labelKey: "themeCustomizer.categorySemantic",
    keys: ["border", "reblog", "favourite"],
  },
];

const COLOR_LABEL_KEYS: Record<keyof ThemeColors, string> = {
  "bg-primary": "themeCustomizer.bgPrimary",
  "bg-secondary": "themeCustomizer.bgSecondary",
  "bg-card": "themeCustomizer.bgCard",
  "text-primary": "themeCustomizer.textPrimary",
  "text-secondary": "themeCustomizer.textSecondary",
  accent: "themeCustomizer.accent",
  "accent-hover": "themeCustomizer.accentHover",
  "accent-text": "themeCustomizer.accentText",
  border: "themeCustomizer.border",
  reblog: "themeCustomizer.reblog",
  favourite: "themeCustomizer.favourite",
};

function currentColors(): ThemeColors {
  return customColors() || PRESET_COLORS[theme() as Theme];
}

function updateColor(key: keyof ThemeColors, value: string) {
  const current = currentColors();
  setCustomColors({ ...current, [key]: value });
}

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

function parseThemeFromJSON(text: string): ThemeCustomization | null {
  try {
    const obj = JSON.parse(text);
    if (!obj || typeof obj !== "object") return null;
    const colors = obj.colors;
    if (!colors || typeof colors !== "object") return null;
    for (const key of COLOR_KEYS) {
      if (typeof colors[key] !== "string" || !HEX_RE.test(colors[key])) return null;
    }
    const base = obj.base;
    if (base && !["dark", "light", "novel"].includes(base)) return null;
    return {
      base: (base || "dark") as Theme,
      colors,
      name: typeof obj.name === "string" ? obj.name : undefined,
    };
  } catch {
    return null;
  }
}

function parseThemeFromCSS(text: string): ThemeColors | null {
  const colors: Partial<ThemeColors> = {};
  const re = /--([a-z-]+):\s*(#[0-9a-fA-F]{6})/g;
  let match;
  while ((match = re.exec(text))) {
    if (COLOR_KEYS.includes(match[1] as keyof ThemeColors)) {
      colors[match[1] as keyof ThemeColors] = match[2];
    }
  }
  if (Object.keys(colors).length === COLOR_KEYS.length) {
    return colors as ThemeColors;
  }
  return null;
}

function exportJSON(colors: ThemeColors, base: Theme, name: string): string {
  return JSON.stringify(
    { version: 1, base, name: name || undefined, colors },
    null,
    2,
  );
}

function exportCSS(colors: ThemeColors, base: Theme, name: string): string {
  const header = name
    ? `/* Nekonoverse Custom Theme: ${name} (based on ${base}) */`
    : `/* Nekonoverse Custom Theme (based on ${base}) */`;
  const lines = COLOR_KEYS.map((k) => `  --${k}: ${colors[k]};`);
  return `${header}\n:root {\n${lines.join("\n")}\n}\n`;
}

function downloadFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ThemeCustomizer() {
  const { t } = useI18n();
  const [saving, setSaving] = createSignal(false);
  const [saveMessage, setSaveMessage] = createSignal("");
  const [showImport, setShowImport] = createSignal(false);
  const [importText, setImportText] = createSignal("");
  const [importError, setImportError] = createSignal("");

  async function handleSave() {
    setSaving(true);
    setSaveMessage("");
    try {
      const colors = currentColors();
      const customization: ThemeCustomization = {
        base: theme(),
        colors,
        ...(customThemeName() ? { name: customThemeName() } : {}),
      };
      await updateThemeCustomization(customization);
      setSaveMessage(t("themeCustomizer.saved" as any));
      setTimeout(() => setSaveMessage(""), 3000);
    } catch {
      setSaveMessage("Error");
    } finally {
      setSaving(false);
    }
  }

  function handleReset() {
    clearCustomColors();
  }

  function handleExportJSON() {
    const colors = currentColors();
    const content = exportJSON(colors, theme(), customThemeName());
    downloadFile(content, "nekonoverse-theme.json", "application/json");
  }

  function handleExportCSS() {
    const colors = currentColors();
    const content = exportCSS(colors, theme(), customThemeName());
    downloadFile(content, "nekonoverse-theme.css", "text/css");
  }

  function handleImport() {
    setImportError("");
    const text = importText().trim();
    if (!text) return;

    // まず JSON を試す
    const jsonTheme = parseThemeFromJSON(text);
    if (jsonTheme) {
      setTheme(jsonTheme.base);
      setCustomColors(jsonTheme.colors);
      if (jsonTheme.name) setCustomThemeName(jsonTheme.name);
      setImportText("");
      setShowImport(false);
      return;
    }

    // CSS を試す
    const cssColors = parseThemeFromCSS(text);
    if (cssColors) {
      setCustomColors(cssColors);
      setImportText("");
      setShowImport(false);
      return;
    }

    setImportError(t("themeCustomizer.importError" as any));
  }

  function handleFileImport(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setImportText(reader.result as string);
    };
    reader.readAsText(file);
    input.value = "";
  }

  return (
    <div class="theme-customizer">
      <h4>{t("themeCustomizer.colors" as any)}</h4>

      <div class="theme-color-name-row">
        <label>{t("themeCustomizer.themeName" as any)}</label>
        <input
          type="text"
          class="theme-name-input"
          placeholder={t("themeCustomizer.themeNamePlaceholder" as any)}
          value={customThemeName()}
          onInput={(e) => setCustomThemeName(e.currentTarget.value)}
          maxLength={50}
        />
      </div>

      <For each={COLOR_GROUPS}>
        {(group) => (
          <div class="theme-color-category">
            <h5>{t(group.labelKey as any)}</h5>
            <div class="theme-color-grid">
              <For each={group.keys}>
                {(key) => (
                  <div class="theme-color-item">
                    <label>{t(COLOR_LABEL_KEYS[key] as any)}</label>
                    <input
                      type="color"
                      value={currentColors()[key]}
                      onInput={(e) => updateColor(key, e.currentTarget.value)}
                    />
                    <input
                      type="text"
                      value={currentColors()[key]}
                      maxLength={7}
                      onInput={(e) => {
                        const v = e.currentTarget.value;
                        if (HEX_RE.test(v)) updateColor(key, v);
                      }}
                    />
                  </div>
                )}
              </For>
            </div>
          </div>
        )}
      </For>

      <div class="theme-preview-section">
        <h4>{t("themeCustomizer.preview" as any)}</h4>
        <div class="theme-preview-container">
          <div class="note-card" style={{ "margin-bottom": "0" }}>
            <div
              class="note-avatar"
              style={{
                background: `var(--text-secondary)`,
                "border-radius": "50%",
                width: "48px",
                height: "48px",
                "flex-shrink": "0",
              }}
            />
            <div class="note-body">
              <div class="note-header">
                <div class="note-header-text">
                  <strong class="note-display-name">Neko</strong>
                  <span class="note-handle">@neko@example.com</span>
                </div>
              </div>
              <div class="note-content">
                <p>{t("themeCustomizer.sampleText" as any)}</p>
                <p>
                  <a
                    href="#"
                    onClick={(e) => e.preventDefault()}
                    style={{ color: "var(--accent)" }}
                  >
                    #nekonoverse
                  </a>
                </p>
              </div>
              <div class="note-actions" style={{ "margin-top": "8px", display: "flex", gap: "16px" }}>
                <span style={{ color: "var(--text-secondary)", "font-size": "0.9em" }}>Reply</span>
                <span style={{ color: "var(--reblog)", "font-size": "0.9em" }}>Reblog</span>
                <span style={{ color: "var(--favourite)", "font-size": "0.9em" }}>Favourite</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="theme-customizer-actions">
        <button class="btn btn-small" onClick={handleReset}>
          {t("themeCustomizer.resetToPreset" as any)}
        </button>
        <button class="btn btn-small btn-primary" onClick={handleSave} disabled={saving()}>
          {saving() ? "..." : t("themeCustomizer.saveToServer" as any)}
        </button>
        <button class="btn btn-small" onClick={handleExportJSON}>
          {t("themeCustomizer.exportJson" as any)}
        </button>
        <button class="btn btn-small" onClick={handleExportCSS}>
          {t("themeCustomizer.exportCss" as any)}
        </button>
        <button class="btn btn-small" onClick={() => setShowImport(!showImport())}>
          {t("themeCustomizer.import" as any)}
        </button>
        <Show when={saveMessage()}>
          <span class="theme-save-message">{saveMessage()}</span>
        </Show>
      </div>

      <Show when={showImport()}>
        <div class="theme-import-area">
          <p style={{ "font-size": "0.85em", color: "var(--text-secondary)", "margin-bottom": "8px" }}>
            {t("themeCustomizer.importHint" as any)}
          </p>
          <textarea
            value={importText()}
            onInput={(e) => setImportText(e.currentTarget.value)}
            placeholder="{ ... } or :root { ... }"
            rows={6}
          />
          <div style={{ display: "flex", gap: "8px", "margin-top": "8px", "align-items": "center" }}>
            <input type="file" accept=".json,.css,.txt" onChange={handleFileImport} />
            <button class="btn btn-small btn-primary" onClick={handleImport}>
              {t("themeCustomizer.import" as any)}
            </button>
          </div>
          <Show when={importError()}>
            <p style={{ color: "var(--accent)", "font-size": "0.85em", "margin-top": "4px" }}>
              {importError()}
            </p>
          </Show>
        </div>
      </Show>
    </div>
  );
}
