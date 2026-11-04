import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col justify-center px-5 text-center">
      <p className="text-[11px] text-muted">404</p>
      <h1 className="mt-2 text-[28px] font-semibold tracking-tight text-ink">
        Nothing here
      </h1>
      <p className="mt-2 text-[13px] leading-relaxed text-muted">
        This page does not exist, or the review was removed.
      </p>
      <Link
        to="/"
        className="mx-auto mt-6 rounded-md bg-accent px-3.5 py-1.5 text-[12.5px] font-medium text-onaccent transition hover:bg-accenth"
      >
        Back to the workspace
      </Link>
    </div>
  )
}
