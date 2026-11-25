import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import CourseQA from './CourseQA'
import App from './App'
import { response, deferred } from './test/fixtures'

const question = {
  id: 12,
  author_id: 1,
  author_name: 'Alex',
  course_code: 'CSC 510',
  title: 'How do projects work?',
  body: 'How should we prepare?',
  helpful_answer_id: null,
  answer_count: 1,
}
const answer = {
  id: 45,
  author_id: 2,
  author_name: 'Jordan',
  body: 'Read the rubric together.',
}
const detail = { question, answers: [answer] }

function respond(data) {
  return response(data)
}

describe('course Q&A', () => {
  it('searches by course, text and helpful-answer status and loads the next page', async () => {
    const user = userEvent.setup()
    fetch
      .mockResolvedValueOnce(
        respond({ questions: [question], next_before: 12 }),
      )
      .mockResolvedValueOnce(
        respond({
          questions: [{ ...question, id: 11, title: 'Older question' }],
          next_before: null,
        }),
      )
      .mockResolvedValueOnce(respond({ questions: [], next_before: null }))
    render(<CourseQA user={{ id: 1 }} />)
    expect(
      await screen.findByRole('link', { name: question.title }),
    ).toHaveAttribute('href', '#/app/qa/12')
    await user.click(
      screen.getByRole('button', { name: 'Load more questions' }),
    )
    expect(
      await screen.findByRole('link', { name: 'Older question' }),
    ).toBeInTheDocument()
    expect(fetch.mock.calls[1][0]).toContain('before=12')
    await user.type(screen.getByLabelText('Course code'), 'CSC 540')
    await user.type(
      screen.getByLabelText('Search questions and answers'),
      'indexes',
    )
    await user.selectOptions(screen.getByLabelText('Answer status'), 'answered')
    await user.click(screen.getByRole('button', { name: 'Search board' }))
    expect(await screen.findByText(/No questions found/)).toBeInTheDocument()
    expect(fetch.mock.calls[2][0]).toBe(
      '/api/qa/questions?course=CSC+540&q=indexes&status=answered',
    )
  })

  it('posts a question with course and text but no user-supplied identity', async () => {
    const user = userEvent.setup()
    fetch
      .mockResolvedValueOnce(respond({ questions: [], next_before: null }))
      .mockResolvedValueOnce(respond({ question }))
    render(<CourseQA user={{ id: 1 }} />)
    await screen.findByText(/No questions found/)
    await user.type(screen.getByLabelText('Question course code'), 'CSC 510')
    await user.type(screen.getByLabelText('Question title'), question.title)
    await user.type(screen.getByLabelText('Question details'), question.body)
    await user.click(screen.getByRole('button', { name: 'Post question' }))
    await waitFor(() => expect(window.location.hash).toBe('#/app/qa/12'))
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
      course_code: 'CSC 510',
      title: question.title,
      body: question.body,
    })
  })

  it('posts an answer, prevents duplicate clicks while pending and refreshes the thread', async () => {
    const user = userEvent.setup()
    const pending = deferred()
    fetch
      .mockResolvedValueOnce(respond({ question, answers: [] }))
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce(respond(detail))
    render(<CourseQA user={{ id: 2 }} questionId="12" />)
    await screen.findByText(/No answers yet/)
    await user.type(screen.getByLabelText('Your answer'), answer.body)
    await user.dblClick(screen.getByRole('button', { name: 'Post answer' }))
    expect(fetch).toHaveBeenCalledTimes(2)
    pending.resolve(respond({ answer_id: 45 }))
    expect(await screen.findByText(answer.body)).toBeInTheDocument()
    expect(screen.getByLabelText('Your answer')).toHaveValue('')
    expect(
      screen.queryByRole('button', { name: 'Mark as helpful' }),
    ).not.toBeInTheDocument()
  })

  it('lets only the author select and clear a helpful answer', async () => {
    const user = userEvent.setup()
    fetch
      .mockResolvedValueOnce(respond(detail))
      .mockResolvedValueOnce(respond({ helpful_answer_id: 45 }))
      .mockResolvedValueOnce(
        respond({
          ...detail,
          question: { ...question, helpful_answer_id: 45 },
        }),
      )
      .mockResolvedValueOnce(respond({ helpful_answer_id: null }))
      .mockResolvedValueOnce(respond(detail))
    render(<CourseQA user={{ id: 1 }} questionId="12" />)
    await user.click(
      await screen.findByRole('button', { name: 'Mark as helpful' }),
    )
    expect(
      await screen.findByText('Helpful answer selected by the question author'),
    ).toBeInTheDocument()
    await user.click(
      screen.getByRole('button', { name: 'Clear helpful answer' }),
    )
    expect(
      await screen.findByRole('button', { name: 'Mark as helpful' }),
    ).toBeInTheDocument()
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ answer_id: 45 })
    expect(JSON.parse(fetch.mock.calls[3][1].body)).toEqual({ answer_id: null })
  })

  it('keeps the answer draft after a failed save and allows retry', async () => {
    const user = userEvent.setup()
    fetch.mockResolvedValueOnce(respond(detail)).mockResolvedValueOnce({
      ok: false,
      json: async () => ({ error: 'Session expired. Sign in again.' }),
    })
    render(<CourseQA user={{ id: 2 }} questionId="12" />)
    await screen.findByText(answer.body)
    await user.type(screen.getByLabelText('Your answer'), 'My advice')
    await user.click(screen.getByRole('button', { name: 'Post answer' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Session expired',
    )
    expect(screen.getByLabelText('Your answer')).toHaveValue('My advice')
    expect(screen.getByRole('button', { name: 'Post answer' })).toBeEnabled()
  })

  it('shows a failed load and displays stored markup as plain text', async () => {
    fetch.mockResolvedValueOnce(
      respond({
        ...detail,
        answers: [{ ...answer, body: '<script>alert(1)</script>' }],
      }),
    )
    const { unmount } = render(<CourseQA user={{ id: 2 }} questionId="12" />)
    expect(
      await screen.findByText('<script>alert(1)</script>'),
    ).toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    unmount()
    fetch.mockRejectedValueOnce(new Error('Network unavailable'))
    render(<CourseQA user={{ id: 2 }} questionId="99" />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Network unavailable',
    )
    expect(screen.queryByLabelText('Your answer')).not.toBeInTheDocument()
  })

  it('connects the app navigation and route without a page-not-found message', async () => {
    fetch.mockImplementation((path) => {
      if (path === '/api/requests')
        return Promise.resolve(respond({ requests: [] }))
      if (path === '/api/notifications')
        return Promise.resolve(respond({ notifications: [], unread_count: 0 }))
      if (path.startsWith('/api/qa/questions'))
        return Promise.resolve(respond({ questions: [], next_before: null }))
      throw new Error(`Unexpected API path ${path}`)
    })
    render(
      <App
        user={{ id: 1, name: 'Alex' }}
        route="app/qa"
        onLogout={vi.fn()}
        onUserUpdated={vi.fn()}
      />,
    )
    expect(
      await screen.findByRole('heading', { name: 'Course Q&A board' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Page not found')).not.toBeInTheDocument()
    expect(
      within(
        screen.getByRole('navigation', { name: 'Main navigation' }),
      ).getByRole('link', {
        name: 'Course Q&A',
      }),
    ).toHaveAttribute('aria-current', 'page')
  })
})
