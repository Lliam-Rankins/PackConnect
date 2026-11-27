// Turns the API's structured match reasons into short, human-readable labels.
const FIELD_NAMES = {
  advice_topics: 'advice topics',
  skills: 'skills',
  interests: 'interests',
  bio: 'bio',
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

function reasonLabel(reason) {
  switch (reason?.type) {
    case 'keyword': {
      const terms = (reason.terms ?? []).filter(Boolean)
      return terms.length ? `Mentions ${terms.join(', ')}` : null
    }
    case 'semantic': {
      const field =
        FIELD_NAMES[reason.field] ??
        String(reason.field ?? '').replace(/_/g, ' ')
      return field ? `Similar ${field}` : null
    }
    case 'rating':
      return Number.isFinite(reason.average)
        ? `Rated ${reason.average} (${plural(reason.count ?? 0, 'review')})`
        : null
    case 'qa_help':
      return reason.count > 0
        ? `${plural(reason.count, 'helpful Q&A answer')}`
        : null
    case 'capacity':
      return Number.isInteger(reason.free)
        ? reason.free > 0
          ? `${plural(reason.free, 'open slot')}`
          : null
        : 'Accepting requests'
    default:
      return null
  }
}

export function reasonLabels(reasons, limit = 3) {
  if (!Array.isArray(reasons)) return []
  return reasons.map(reasonLabel).filter(Boolean).slice(0, limit)
}
