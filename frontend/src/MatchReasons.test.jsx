import { render, screen, within } from '@testing-library/react'
import { expect, it } from 'vitest'
import MatchReasons from './MatchReasons'

const reasons = [
  { type: 'keyword', terms: ['testing'] },
  { type: 'rating', average: 4.5, count: 3 },
]

it('renders reason chips as a labelled list', () => {
  render(<MatchReasons reasons={reasons} />)
  const list = screen.getByRole('list', { name: 'Why this match' })
  expect(within(list).getAllByRole('listitem')).toHaveLength(2)
  expect(screen.getByText('Mentions testing')).toBeInTheDocument()
  expect(screen.queryByText('Best match')).not.toBeInTheDocument()
})

it('shows the Best match badge when best', () => {
  render(<MatchReasons reasons={reasons} best />)
  expect(screen.getByText('Best match')).toBeInTheDocument()
})

it('caps chips at three', () => {
  render(
    <MatchReasons
      reasons={[
        { type: 'qa_help', count: 2 },
        { type: 'semantic', field: 'bio' },
        { type: 'semantic', field: 'skills' },
        { type: 'semantic', field: 'interests' },
      ]}
    />,
  )
  expect(screen.getAllByRole('listitem')).toHaveLength(3)
})

it('renders nothing without badge or reasons', () => {
  const { container } = render(<MatchReasons reasons={[]} />)
  expect(container).toBeEmptyDOMElement()
})
