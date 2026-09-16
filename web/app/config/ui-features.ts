function enabled(value: string | undefined, fallback = false): boolean {
  if (value === undefined || value === "") return fallback;
  return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

export const uiFeatures = Object.freeze({
  overviewV2: enabled(import.meta.env.VITE_UI_OVERVIEW_V2, true),
  evaluationV2: enabled(import.meta.env.VITE_UI_EVALUATION_V2, true),
  assistantV2: enabled(import.meta.env.VITE_UI_ASSISTANT_V2, true),
  conversationV2: enabled(import.meta.env.VITE_UI_CONVERSATION_V2),
  assetsV2: enabled(import.meta.env.VITE_UI_ASSETS_V2, true),
});
