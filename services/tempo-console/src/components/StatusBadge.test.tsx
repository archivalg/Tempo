import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="completed" />)
    expect(screen.getByText('completed')).toBeInTheDocument()
  })

  it('gives an unrecognised status the info tone rather than throwing', () => {
    render(<StatusBadge status="something_new" />)
    const badge = screen.getByText('something_new')
    expect(badge.className).toContain('badge-info')
  })

  it('maps a bad-tone status correctly', () => {
    render(<StatusBadge status="rejected" />)
    expect(screen.getByText('rejected').className).toContain('badge-bad')
  })
})
