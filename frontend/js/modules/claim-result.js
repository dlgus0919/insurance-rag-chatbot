export function compactClaimBasisItems(items, maxItems = 4) {
  const grouped = [];
  const bySource = new Map();

  for (const rawItem of Array.isArray(items) ? items : []) {
    const source = String(rawItem?.source || '').trim() || '근거';
    const content = String(rawItem?.content || '').trim();
    if (!content) continue;

    const existing = bySource.get(source);
    if (existing) {
      existing.extraCount += 1;
      continue;
    }

    const compacted = {
      source,
      content,
      extraCount: 0,
    };
    bySource.set(source, compacted);
    grouped.push(compacted);
  }

  return grouped.slice(0, maxItems);
}
