export const MODEL_SELECTION_SOURCES = {
  EXPLICIT: 'explicit',
  DEFAULT: 'default',
};

export function resolveSelectedModelForAuthenticatedRoute({
  selectedModel,
  source,
  availableLocalIds,
  defaultLocal,
}) {
  const localIds = Array.isArray(availableLocalIds) ? availableLocalIds.filter(Boolean) : [];
  const fallbackDefault = defaultLocal || localIds[0] || '';

  if (!fallbackDefault) {
    return { model: selectedModel || '', source: source || '' };
  }

  if (
    source === MODEL_SELECTION_SOURCES.EXPLICIT &&
    selectedModel &&
    localIds.includes(selectedModel)
  ) {
    return { model: selectedModel, source };
  }

  if (
    source === MODEL_SELECTION_SOURCES.DEFAULT &&
    selectedModel === fallbackDefault
  ) {
    return { model: selectedModel, source };
  }

  return {
    model: fallbackDefault,
    source: MODEL_SELECTION_SOURCES.DEFAULT,
  };
}
