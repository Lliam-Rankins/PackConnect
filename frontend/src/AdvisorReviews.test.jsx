import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AdviceReviewForm, AdvisorReviews } from './AdvisorReviews'
import { Conversation, RequestInbox } from './Messaging'
import { deferred, request, response, student } from './test/fixtures'

vi.mock('./MeetingPanel', () => ({ default: () => null }))

const completed = { ...request, status: 'completed' }
const requester = { id: request.sender_id, name: request.sender_name }

describe('advisor review workflow', () => {
  it('submits from completed outgoing requests once and shows the saved review', async () => {
    const user = userEvent.setup()
    const pending = deferred()
    fetch.mockReturnValue(pending.promise)
    render(
      <RequestInbox
        user={requester}
        requests={[completed]}
        initialTab="outgoing"
        loading={false}
        error=""
        onRefresh={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: 'Submit review' })).toBeDisabled()
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Advice helpfulness' }),
      '5',
    )
    await user.type(
      screen.getByRole('textbox', { name: 'Feedback (optional)' }),
      'Useful project tips.',
    )
    await user.dblClick(screen.getByRole('button', { name: 'Submit review' }))
    expect(
      screen.getByRole('button', { name: 'Submitting review...' }),
    ).toBeDisabled()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith(
      '/api/requests/7/review',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ rating: 5, comment: 'Useful project tips.' }),
      }),
    )
    pending.resolve(
      response({ review: { rating: 5, comment: 'Useful project tips.' } }, 201),
    )
    expect(
      await screen.findByRole('heading', { name: 'Your review for CSC 510' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Useful project tips.')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'View advisor feedback' }),
    ).toHaveAttribute('href', '#/app/students/1')
    expect(
      screen.queryByRole('button', { name: 'Submit review' }),
    ).not.toBeInTheDocument()
  })

  it.each([
    'pending',
    'accepted',
    'declined',
    'cancelled',
    'expired',
    'closed',
  ])('keeps review submission unavailable for %s requests', (status) => {
    render(
      <RequestInbox
        user={requester}
        requests={[{ ...request, status }]}
        initialTab="outgoing"
        loading={false}
        error=""
        onRefresh={vi.fn()}
      />,
    )
    expect(
      screen.queryByRole('button', { name: 'Submit review' }),
    ).not.toBeInTheDocument()
  })

  it('keeps review submission unavailable to the advisor', () => {
    render(
      <RequestInbox
        user={student}
        requests={[completed]}
        loading={false}
        error=""
        onRefresh={vi.fn()}
      />,
    )
    expect(
      screen.getByRole('link', { name: 'View message history' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Submit review' }),
    ).not.toBeInTheDocument()
  })

  it('retains feedback and displays server rejection without claiming success', async () => {
    const user = userEvent.setup()
    fetch.mockResolvedValue(
      response({ error: 'You already reviewed this advice request.' }, 409),
    )
    render(<AdviceReviewForm record={completed} />)
    await user.selectOptions(screen.getByRole('combobox'), '4')
    await user.type(screen.getByRole('textbox'), 'Helpful examples.')
    await user.click(screen.getByRole('button', { name: 'Submit review' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'You already reviewed this advice request.',
    )
    expect(screen.getByRole('combobox')).toHaveValue('4')
    expect(screen.getByRole('textbox')).toHaveValue('Helpful examples.')
    expect(screen.getByRole('button', { name: 'Submit review' })).toBeEnabled()
  })

  it('shows an existing review after reloading the request', () => {
    render(
      <AdviceReviewForm
        record={{
          ...completed,
          review_rating: 3,
          review_comment: 'Saved feedback',
        }}
      />,
    )
    expect(screen.getByText('Advice helpfulness 3 / 5')).toBeInTheDocument()
    expect(screen.getByText('Saved feedback')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Submit review' }),
    ).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('offers a review from completed conversation history', async () => {
    fetch.mockResolvedValue(
      response({ request: completed, messages: [], has_more: false }),
    )
    render(<Conversation requestId={7} user={requester} />)
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Submit review' }),
      ).toBeInTheDocument(),
    )
    expect(
      screen.queryByRole('button', { name: 'Send message' }),
    ).not.toBeInTheDocument()
  })
})

describe('advisor profile feedback', () => {
  it('shows a new advisor as unrated', () => {
    render(
      <AdvisorReviews
        student={{
          review_summary: { review_count: 0, average_rating: null },
          reviews: [],
        }}
      />,
    )
    expect(screen.getByText('No reviews yet.')).toBeInTheDocument()
  })

  it('shows the average, count, and feedback with its course', () => {
    render(
      <AdvisorReviews
        student={{
          review_summary: { review_count: 2, average_rating: 3.5 },
          reviews: [
            {
              request_id: 7,
              rating: 5,
              course_code: 'CSC 510',
              comment: 'Clear explanations.',
              created_at: request.created_at,
            },
            {
              request_id: 8,
              rating: 2,
              course_code: 'CSC 540',
              comment: '',
              created_at: request.created_at,
            },
          ],
        }}
      />,
    )
    expect(screen.getByText('3.5 / 5')).toBeInTheDocument()
    expect(screen.getByText('2 reviews')).toBeInTheDocument()
    expect(screen.getByText('CSC 510')).toBeInTheDocument()
    expect(screen.getByText('CSC 540')).toBeInTheDocument()
    expect(screen.getByText('Clear explanations.')).toBeInTheDocument()
  })
})
