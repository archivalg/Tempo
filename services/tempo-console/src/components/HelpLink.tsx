import { Link } from 'react-router-dom'

/** A small "Help" link to the article for the page you are on. */
export function HelpLink({ id, label = 'Help with this page' }: { id: string; label?: string }) {
  return <Link to={`/help/${id}`} className="tp-btn" style={{ textDecoration: 'none' }} aria-label={label}>? Help</Link>
}
