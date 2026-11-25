import { useEffect, useState } from 'react'
import { api, json } from './messagingApi'
import './CourseQA.css'

export default function CourseQA({ user, questionId }) {
  const [questions, setQuestions] = useState([])
  const [detail, setDetail] = useState(null)
  const [filters, setFilters] = useState({ course: '', q: '', status: 'all' })
  const [applied, setApplied] = useState(filters)
  const [next, setNext] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [draft, setDraft] = useState({ course_code: '', title: '', body: '' })
  const [answer, setAnswer] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const path = questionId
      ? `/api/qa/questions/${questionId}`
      : `/api/qa/questions?${new URLSearchParams(applied)}`
    api(path, { signal: controller.signal })
      .then((data) => {
        if (questionId) setDetail(data)
        else {
          setQuestions(data.questions)
          setNext(data.next_before)
        }
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err.message)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [questionId, applied])

  async function submitQuestion(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const data = await api('/api/qa/questions', json('POST', draft))
      window.location.hash = `/app/qa/${data.question.id}`
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function mutate(path, method, body, message) {
    if (busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await api(path, json(method, body))
      // Clear submitted text before refresh, so a failed refresh cannot invite a duplicate answer.
      if (method === 'POST') setAnswer('')
      setNotice(message)
      setDetail(await api(`/api/qa/questions/${questionId}`))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function loadMore() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const data = await api(
        `/api/qa/questions?${new URLSearchParams({ ...applied, before: next })}`,
      )
      setQuestions((rows) => [...rows, ...data.questions])
      setNext(data.next_before)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="course-qa" aria-labelledby="qa-heading">
      <h1 id="qa-heading">Course Q&amp;A board</h1>
      <p>
        Share course advice that other PackConnect members can find again. Posts
        are visible to signed-in members. Keep personal information out of
        posts.
      </p>
      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {loading && <p role="status">Loading course questions...</p>}
      {!questionId && (
        <>
          <form
            aria-label="Search course questions"
            className="qa-filters"
            onSubmit={(event) => {
              event.preventDefault()
              setError('')
              setQuestions([])
              setNext(null)
              setLoading(true)
              setApplied({ ...filters })
            }}
          >
            <label>
              Course code
              <input
                value={filters.course}
                maxLength={30}
                placeholder="CSC 510"
                onChange={(e) =>
                  setFilters({ ...filters, course: e.target.value })
                }
              />
            </label>
            <label>
              Search questions and answers
              <input
                value={filters.q}
                maxLength={200}
                onChange={(e) => setFilters({ ...filters, q: e.target.value })}
              />
            </label>
            <label>
              Answer status
              <select
                value={filters.status}
                onChange={(e) =>
                  setFilters({ ...filters, status: e.target.value })
                }
              >
                <option value="all">All questions</option>
                <option value="answered">Helpful answer selected</option>
                <option value="unanswered">No helpful answer yet</option>
              </select>
            </label>
            <button type="submit" disabled={busy || loading}>
              Search board
            </button>
          </form>
          {!loading && questions.length === 0 && (
            <p>No questions found. Ask the first question for your course.</p>
          )}
          <ul className="qa-list">
            {questions.map((q) => (
              <li key={q.id}>
                <a href={`#/app/qa/${q.id}`}>{q.title}</a>
                <p>
                  {q.course_code} · {q.author_name} · {q.answer_count}{' '}
                  {q.answer_count === 1 ? 'answer' : 'answers'}
                  {q.helpful_answer_id ? ' · Helpful answer selected' : ''}
                </p>
              </li>
            ))}
          </ul>
          {next && (
            <button type="button" onClick={loadMore} disabled={busy || loading}>
              Load more questions
            </button>
          )}
          <form
            aria-label="Ask a course question"
            className="qa-post"
            onSubmit={submitQuestion}
          >
            <h2>Ask a course question</h2>
            <label>
              Question course code
              <input
                required
                maxLength={30}
                placeholder="CSC 510"
                value={draft.course_code}
                onChange={(e) =>
                  setDraft({ ...draft, course_code: e.target.value })
                }
              />
            </label>
            <label>
              Question title
              <input
                required
                maxLength={160}
                value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              />
            </label>
            <label>
              Question details
              <textarea
                required
                maxLength={4000}
                rows={4}
                value={draft.body}
                onChange={(e) => setDraft({ ...draft, body: e.target.value })}
              />
            </label>
            <button
              disabled={
                busy ||
                !draft.title.trim() ||
                !draft.body.trim() ||
                !draft.course_code.trim()
              }
            >
              {busy ? 'Posting...' : 'Post question'}
            </button>
          </form>
        </>
      )}
      {questionId && <a href="#/app/qa">Back to course questions</a>}
      {questionId && detail && (
        <>
          <article className="qa-post">
            <h2>{detail.question.title}</h2>
            <p>
              {detail.question.course_code} · Asked by{' '}
              {detail.question.author_name}
            </p>
            <p className="qa-body">{detail.question.body}</p>
          </article>
          <h2>Answers</h2>
          {detail.answers.length === 0 && (
            <p>No answers yet. Share your experience with this course.</p>
          )}
          {detail.answers.map((a) => (
            <article
              className="qa-post"
              key={a.id}
              aria-label={`Answer by ${a.author_name}`}
            >
              <h3>{a.author_name}</h3>
              <p className="qa-body">{a.body}</p>
              {detail.question.helpful_answer_id === a.id && (
                <p className="qa-helpful">
                  Helpful answer selected by the question author
                </p>
              )}
              {detail.question.author_id === user.id && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    mutate(
                      `/api/qa/questions/${questionId}/helpful-answer`,
                      'PUT',
                      {
                        answer_id:
                          detail.question.helpful_answer_id === a.id
                            ? null
                            : a.id,
                      },
                      'Helpful answer updated.',
                    )
                  }
                >
                  {detail.question.helpful_answer_id === a.id
                    ? 'Clear helpful answer'
                    : 'Mark as helpful'}
                </button>
              )}
            </article>
          ))}
          {detail.answers.length < 200 ? (
            <form
              aria-label="Answer this question"
              className="qa-post"
              onSubmit={(event) => {
                event.preventDefault()
                mutate(
                  `/api/qa/questions/${questionId}/answers`,
                  'POST',
                  { body: answer },
                  'Your answer was posted.',
                )
              }}
            >
              <label>
                Your answer
                <textarea
                  required
                  rows={4}
                  maxLength={4000}
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                />
              </label>
              <button disabled={busy || !answer.trim()}>
                {busy ? 'Saving...' : 'Post answer'}
              </button>
            </form>
          ) : (
            <p>This question has reached its 200-answer limit.</p>
          )}
        </>
      )}
    </section>
  )
}
