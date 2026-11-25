import { useId, useState } from 'react'
import { api, json } from './messagingApi'
import './AdvisorReviews.css'

export function AdviceReviewForm({ record }) {
  const headingId = useId()
  const [rating, setRating] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(null)
  const submitted =
    saved ||
    (record.review_rating != null
      ? { rating: record.review_rating, comment: record.review_comment }
      : null)

  async function submit(event) {
    event.preventDefault()
    if (busy || !rating) return
    setBusy(true)
    setError('')
    try {
      const data = await api(
        `/api/requests/${record.id}/review`,
        json('POST', { rating: Number(rating), comment }),
      )
      setSaved(data.review)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (submitted)
    return (
      <section className="advice-review" aria-labelledby={headingId}>
        <h3 id={headingId}>Your review for {record.course_code}</h3>
        <p>Advice helpfulness {submitted.rating} / 5</p>
        {submitted.comment && (
          <p className="preserve-lines">{submitted.comment}</p>
        )}
        <a href={`#/app/students/${record.recipient_id}`}>
          View advisor feedback
        </a>
      </section>
    )

  return (
    <form
      className="advice-review"
      onSubmit={submit}
      aria-labelledby={headingId}
    >
      <h3 id={headingId}>Review advice for {record.course_code}</h3>
      <p className="profile-note">
        Your rating, comment, and course will appear on the advisor's profile.
        Each completed request allows one review.
      </p>
      <fieldset className="review-fields" disabled={busy}>
        <label>
          Advice helpfulness
          <select
            value={rating}
            onChange={(event) => setRating(event.target.value)}
            required
          >
            <option value="">Choose a rating</option>
            <option value="1">1 — Not helpful</option>
            <option value="2">2 — Slightly helpful</option>
            <option value="3">3 — Moderately helpful</option>
            <option value="4">4 — Helpful</option>
            <option value="5">5 — Very helpful</option>
          </select>
        </label>
        <label>
          Feedback (optional)
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={1000}
            rows={3}
            placeholder="What helped you with this course?"
          />
        </label>
        {error && (
          <p className="error-message" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={!rating}>
          {busy ? 'Submitting review...' : 'Submit review'}
        </button>
      </fieldset>
    </form>
  )
}

export function AdvisorReviews({ student }) {
  const headingId = useId()
  const { review_count = 0, average_rating = null } =
    student.review_summary || {}
  const reviews = student.reviews || []
  return (
    <section className="advisor-reviews" aria-labelledby={headingId}>
      <h3 id={headingId}>Advice helpfulness</h3>
      {review_count === 0 ? (
        <p className="profile-note">No reviews yet.</p>
      ) : (
        <>
          <p className="review-summary">
            <strong>{Number(average_rating).toFixed(1)} / 5</strong>
            <span>
              {review_count} {review_count === 1 ? 'review' : 'reviews'}
            </span>
          </p>
          <div className="review-list">
            {reviews.map((review) => (
              <article className="advisor-review" key={review.request_id}>
                <div className="review-heading">
                  <strong>{review.course_code}</strong>
                  <span>{review.rating} / 5</span>
                  <time dateTime={review.created_at}>
                    {new Date(review.created_at).toLocaleDateString()}
                  </time>
                </div>
                {review.comment && (
                  <p className="preserve-lines">{review.comment}</p>
                )}
              </article>
            ))}
          </div>
          {review_count > reviews.length && (
            <p className="profile-note">
              Showing the latest {reviews.length} reviews.
            </p>
          )}
        </>
      )}
    </section>
  )
}
