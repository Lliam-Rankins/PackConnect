import { describe, expect, it } from 'vitest'
import { reasonLabels } from './matchReasons'

describe('reasonLabels', () => {
  it('formats each reason type', () => {
    expect(
      reasonLabels(
        [
          { type: 'keyword', terms: ['testing', 'flask'] },
          { type: 'semantic', field: 'advice_topics' },
          { type: 'rating', average: 4.5, count: 3 },
          { type: 'qa_help', count: 2 },
          { type: 'capacity', free: 2 },
        ],
        10,
      ),
    ).toEqual([
      'Mentions testing, flask',
      'Similar advice topics',
      'Rated 4.5 (3 reviews)',
      '2 helpful Q&A answers',
      '2 open slots',
    ])
  })

  it('limits to three labels by default', () => {
    const reasons = [
      { type: 'qa_help', count: 1 },
      { type: 'semantic', field: 'bio' },
      { type: 'semantic', field: 'skills' },
      { type: 'semantic', field: 'interests' },
    ]
    expect(reasonLabels(reasons)).toHaveLength(3)
    expect(reasonLabels(reasons, 2)).toHaveLength(2)
  })

  it('ignores unknown or malformed reasons', () => {
    expect(
      reasonLabels([{ type: 'mystery' }, null, { type: 'keyword', terms: [] }]),
    ).toEqual([])
    expect(reasonLabels(undefined)).toEqual([])
  })

  it('uses singular forms and humanizes unknown fields', () => {
    expect(
      reasonLabels([
        { type: 'rating', average: 5, count: 1 },
        { type: 'qa_help', count: 1 },
        { type: 'capacity', free: 1 },
        { type: 'semantic', field: 'side_projects' },
      ]),
    ).toEqual(['Rated 5 (1 review)', '1 helpful Q&A answer', '1 open slot'])
  })

  it('shows accepting requests when there is no limit', () => {
    expect(reasonLabels([{ type: 'capacity', free: null }])).toEqual([
      'Accepting requests',
    ])
  })
})
