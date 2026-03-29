import { createSignal, createEffect, Show } from "solid-js";
import { useI18n } from "@nekonoverse/ui/i18n";
import { getTerms } from "@nekonoverse/ui/api/instance";
import DOMPurify from "dompurify";

export default function Terms() {
  const { t } = useI18n();
  const [html, setHtml] = createSignal<string | null>(null);
  const [loaded, setLoaded] = createSignal(false);

  createEffect(() => {
    (async () => {
      try {
        const data = await getTerms();
        if (data.content_html) {
          setHtml(
            DOMPurify.sanitize(data.content_html, {
              ALLOWED_TAGS: [
                "h1", "h2", "h3", "h4", "h5", "h6",
                "p", "br", "hr",
                "strong", "em", "code", "pre", "blockquote",
                "ul", "ol", "li",
                "a",
                "table", "thead", "tbody", "tr", "th", "td",
              ],
              ALLOWED_ATTR: ["href"],
            }),
          );
        }
      } catch {
        // 無視
      }
      setLoaded(true);
    })();
  });

  return (
    <div class="legal-page">
      <h1>{t("legal.terms")}</h1>
      <Show when={loaded()}>
        <Show when={html()} fallback={<p class="legal-not-set">{t("legal.notSet")}</p>}>
          <div class="legal-content" innerHTML={html()!} />
        </Show>
      </Show>
    </div>
  );
}
