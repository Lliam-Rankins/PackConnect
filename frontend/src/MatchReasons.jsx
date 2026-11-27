import { reasonLabels } from './matchReasons'
import './MatchReasons.css'

function MatchReasons({ reasons, best = false }) {
  const labels = reasonLabels(reasons)
  if (!best && !labels.length) return null

  return (
    <div className="match-reasons">
      {best && <span className="best-match-badge">Best match</span>}
      {labels.length > 0 && (
        <ul className="match-reason-list" aria-label="Why this match">
          {labels.map((label) => (
            <li key={label}>{label}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default MatchReasons
