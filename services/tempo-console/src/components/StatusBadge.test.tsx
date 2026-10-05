import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="completed" />)
    expect(screen.getByText('completed')).toBeInTheDocument()
  })

  it('gives an unrecognised status the neutral Tempo tone rather than throwing', () => {
    render(<StatusBadge status="something_new" />)
    const badge = screen.getByText('something new')
    expect(badge.className).toContain('tp-badge')
    expect(badge.className).toContain('neutral')
  })

  it('maps a bad-tone status correctly', () => {
    render(<StatusBadge status="rejected" />)
    const badge = screen.getByText('rejected')
    expect(badge.className).toContain('tp-badge')
    expect(badge.className).toContain('bad')
  })
})
