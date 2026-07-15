import { useI18n } from "../i18n";

/** 未实现的 nav 目标（traces/tools/prompts/settings）占位。 */
export default function Placeholder() {
  const { t } = useI18n();
  return (
    <div className="p-8">
      <h1 className="text-xl font-semibold">{t("nav.tools")}</h1>
      <p className="text-ink-mute mt-2 text-sm">🚧 v0.1.0 — coming soon.</p>
    </div>
  );
}
